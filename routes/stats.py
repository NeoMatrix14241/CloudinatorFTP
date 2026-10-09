"""
routes/stats.py - storage stats (+SSE, polling), monitoring, disk, health_check, event-loop
watchdog (the only before_serving hook), /api/search and the speedtest routes
(Phase 6 of the split, CLAUDE.md 4.74).

Moved verbatim from app.py. Gets shared objects via `from core import ...` (the file monitor is
core.file_monitor; init_file_monitor() stays in core.py); imports no other route module.
"""

from core import app, file_monitor, login_required

from quart import jsonify, request, send_file, session
import os
import sys
import io
import asyncio
import threading
import time
from config import ROOT_DIR, ENABLE_SEARCH_INDEX
from auth import current_user, is_logged_in
import storage
from search_index import search_index_manager
from realtime_stats import storage_stats_sse, get_event_manager


@app.route("/api/storage_stats", methods=["GET"])
@login_required
async def storage_stats_api():
    """Get storage statistics - INSTANT VERSION using cached data"""
    try:
        print(
            f"📊 INSTANT Storage stats API called by user: {session.get('username', 'unknown')}"
        )

        # Use cached snapshot for instant response
        from file_monitor import get_file_monitor

        file_monitor = get_file_monitor()
        current_snapshot = file_monitor.get_current_snapshot()

        # Get fast disk stats only (no file counting)
        from realtime_stats import StorageStatsEventManager

        event_manager = StorageStatsEventManager()
        disk_stats = event_manager._get_fast_disk_stats()

        # Build instant stats response
        if current_snapshot:
            stats = {
                "total_space": disk_stats["total_space"],
                "used_space": disk_stats["used_space"],
                "free_space": disk_stats["free_space"],
                "file_count": current_snapshot.file_count,
                "dir_count": current_snapshot.dir_count,
                "content_size": current_snapshot.total_size,
            }
        else:
            # Fallback instant stats
            stats = {
                "total_space": disk_stats["total_space"],
                "used_space": disk_stats["used_space"],
                "free_space": disk_stats["free_space"],
                "file_count": 0,
                "dir_count": 0,
                "content_size": 0,
            }

        print(
            f"📊 INSTANT storage stats returned: files={stats['file_count']}, dirs={stats['dir_count']}"
        )
        return jsonify(stats), 200

    except Exception as e:
        print(f"❌ Error getting instant storage stats: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": f"Storage stats error: {str(e)}"}), 500


@app.route("/api/storage_stats_slow", methods=["GET"])
@login_required
async def storage_stats_slow_api():
    """Get storage statistics - SLOW VERSION with full file counting"""
    try:
        print(
            f"📊 SLOW Storage stats API called by user: {session.get('username', 'unknown')}"
        )
        stats = storage.get_storage_stats()
        print(f"📊 SLOW storage stats calculated: {stats}")
        return jsonify(stats), 200

    except Exception as e:
        print(f"❌ Error getting slow storage stats: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": f"Storage stats error: {str(e)}"}), 500


@app.route("/api/storage_stats_debug", methods=["GET"])
async def storage_stats_debug():
    """Debug version of storage stats without authentication"""
    try:
        print("🔧 Debug storage stats API called (no auth required)")
        stats = storage.get_storage_stats()
        print(f"🔧 Debug storage stats calculated: {stats}")
        return (
            jsonify(
                {
                    "debug": True,
                    "platform": os.name,
                    "has_statvfs": hasattr(os, "statvfs"),
                    "root_dir": storage.ROOT_DIR,
                    "stats": stats,
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Error in debug storage stats: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": f"Debug storage stats error: {str(e)}"}), 500


@app.route("/api/storage_stats_stream", methods=["GET"])
async def storage_stats_stream():
    """Server-Sent Events endpoint for real-time storage stats"""
    if not is_logged_in():
        return jsonify({"error": "Authentication required"}), 401

    print(f"📡 SSE connection established for user: {current_user()}")
    return await storage_stats_sse()


@app.route("/api/storage_stats_poll", methods=["GET"])
async def storage_stats_poll():
    """Polling endpoint for storage stats - fallback when SSE fails"""
    if not is_logged_in():
        return jsonify({"error": "Authentication required"}), 401

    try:
        from file_monitor import get_file_monitor

        file_monitor = get_file_monitor()

        # Get current timestamp for comparison
        last_check = request.args.get("last_check", type=float, default=0)

        # For initial load (last_check=0), provide instant cached stats
        if last_check == 0:
            print("📊 Initial polling request - providing instant cached stats")
            current_time = time.time()

            # Get quick disk stats only
            from realtime_stats import StorageStatsEventManager

            event_manager = StorageStatsEventManager()
            disk_stats = event_manager._get_fast_disk_stats()

            # Use cached snapshot if available, otherwise provide placeholder
            current_snapshot = file_monitor.get_current_snapshot()
            if current_snapshot:
                file_count = current_snapshot.file_count
                dir_count = current_snapshot.dir_count
                total_size = current_snapshot.total_size
            else:
                # Provide instant placeholder stats
                file_count = 0
                dir_count = 0
                total_size = 0

            response_data = {
                "type": "polling_response",
                "timestamp": current_time,
                "changed": True,  # Always true for initial load
                "data": {
                    "file_count": file_count,
                    "dir_count": dir_count,
                    "total_size": total_size,
                    "content_size": total_size,
                    "last_modified": current_time,
                    "total_space": disk_stats["total_space"],
                    "free_space": disk_stats["free_space"],
                    "used_space": disk_stats["used_space"],
                    "changes": {
                        "files_changed": 0,
                        "dirs_changed": 0,
                        "size_changed": 0,
                        "content_changed": False,
                        "mtime_changed": False,
                    },
                },
            }

            response_data.update(file_monitor.seq_info())  # 4.67: baseline for last_seq
            print(f"📊 Instant polling response: files={file_count}, dirs={dir_count}")
            return jsonify(response_data), 200

        # Regular polling check for changes
        current_snapshot = file_monitor.get_current_snapshot()
        current_time = time.time()

        # Always return current stats, but include a 'changed' flag
        has_changes = False
        changes_data = {"files_changed": 0, "dirs_changed": 0, "size_changed": 0}

        if current_snapshot and current_snapshot.timestamp > last_check:
            has_changes = True

            # Get the last known file/dir counts from the polling history
            # Use a simple session-based tracking to reduce false positives
            last_known_files = request.args.get("last_files", type=int, default=0)
            last_known_dirs = request.args.get("last_dirs", type=int, default=0)

            # Calculate actual count changes
            files_diff = (
                current_snapshot.file_count - last_known_files
                if last_known_files > 0
                else 0
            )
            dirs_diff = (
                current_snapshot.dir_count - last_known_dirs
                if last_known_dirs > 0
                else 0
            )

            # Only report specific changes if we have meaningful differences
            if abs(files_diff) > 0 or abs(dirs_diff) > 0:
                # Real file/folder count change detected
                changes_data = {
                    "files_changed": files_diff,
                    "dirs_changed": dirs_diff,
                    "size_changed": 0,  # Size changes are complex to calculate
                    "content_changed": True,
                    "mtime_changed": True,
                }
            else:
                # Timestamp changed but no count changes - likely system noise
                # Report as minor content change without specific counts
                changes_data = {
                    "files_changed": 0,  # No count change
                    "dirs_changed": 0,  # No count change
                    "size_changed": 0,  # No size change claimed
                    "content_changed": True,  # Something changed (timestamp)
                    "mtime_changed": True,  # Modification time changed
                }

        # 4.67: a client that sends last_seq gets change detection from the monitor's
        # change sequence instead of "the snapshot is newer than last_check" (that was
        # true after EVERY batch and made polling mode refresh the table non-stop).
        # changed / content_changed are true only when something really changed, and
        # the folders that changed ride along as changed_dirs. Old clients (no
        # last_seq) keep the previous behaviour above.
        seq_extra = {}
        seq_arg = request.args.get("last_seq", type=int)
        if seq_arg is not None and current_snapshot:
            info = file_monitor.changes_since(seq_arg, request.args.get("seq_epoch"))
            lf = request.args.get("last_files", type=int, default=0)
            ld = request.args.get("last_dirs", type=int, default=0)
            ls = request.args.get("last_size", type=int, default=0)
            files_diff = current_snapshot.file_count - lf if lf > 0 else 0
            dirs_diff = current_snapshot.dir_count - ld if ld > 0 else 0
            size_diff = current_snapshot.total_size - ls if ls > 0 else 0
            counts_moved = bool(files_diff or dirs_diff or size_diff)
            has_changes = bool(info["changed"] or counts_moved)
            changes_data = {
                "files_changed": files_diff,
                "dirs_changed": dirs_diff,
                "size_changed": size_diff,
                "content_changed": counts_moved,
                "mtime_changed": False,
            }
            seq_extra = {
                "change_seq": info["change_seq"],
                "seq_epoch": info["seq_epoch"],
                "changed_dirs": info["dirs"],
                "changed_dirs_truncated": bool(info["everything"] or info["truncated"]),
            }

        # Debug logging for timestamp comparison
        print(
            f"📊 Polling debug: last_check={last_check}, snapshot_timestamp={current_snapshot.timestamp if current_snapshot else 'None'}, has_changes={has_changes}"
        )

        # Get disk stats
        from realtime_stats import StorageStatsEventManager

        event_manager = StorageStatsEventManager()
        disk_stats = event_manager._get_fast_disk_stats()

        response_data = {
            "type": "polling_response",
            "timestamp": current_time,
            "changed": has_changes,
            "data": {
                "file_count": current_snapshot.file_count if current_snapshot else 0,
                "dir_count": current_snapshot.dir_count if current_snapshot else 0,
                "total_size": current_snapshot.total_size if current_snapshot else 0,
                "content_size": current_snapshot.total_size if current_snapshot else 0,
                "last_modified": (
                    current_snapshot.last_modified if current_snapshot else current_time
                ),
                "total_space": disk_stats["total_space"],
                "free_space": disk_stats["free_space"],
                "used_space": disk_stats["used_space"],
                "changes": changes_data,  # Add changes field for frontend
            },
        }

        # a client without last_seq still gets a baseline, so its NEXT poll can use it
        response_data.update(seq_extra or file_monitor.seq_info())
        print(
            f"📊 Polling response: changed={has_changes}, files={response_data['data']['file_count']}"
        )
        return jsonify(response_data), 200

    except Exception as e:
        print(f"❌ Error in polling endpoint: {e}")
        return jsonify({"error": f"Polling error: {str(e)}"}), 500


@app.route("/api/monitoring_status", methods=["GET"])
async def monitoring_status():
    """Get current monitoring system status"""
    if not is_logged_in():
        return jsonify({"error": "Authentication required"}), 401

    try:
        event_manager = get_event_manager()
        return (
            jsonify(
                {
                    "monitoring_active": file_monitor.monitoring,
                    "connected_clients": event_manager.get_client_count(),
                    "last_check": getattr(file_monitor, "last_check_time", None),
                    "total_checks": getattr(file_monitor, "check_count", 0),
                }
            ),
            200,
        )
    except Exception as e:
        print(f"❌ Error getting monitoring status: {e}")
        return jsonify({"error": f"Monitoring status error: {str(e)}"}), 500


@app.route("/api/disk_stats_fast", methods=["GET"])
async def disk_stats_fast():
    """Fast disk stats only (no file counting) - no auth required"""
    try:
        print("📊 Fast disk stats request")

        # Get only disk usage stats, skip file counting
        disk_usage_path = storage.ROOT_DIR

        # Special handling for Android/Termux
        if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
            android_storage_paths = [
                "/storage/emulated/0",
                "/sdcard",
                "/storage/self/primary",
            ]

            for path in android_storage_paths:
                if os.path.exists(path) and os.access(path, os.R_OK):
                    disk_usage_path = path
                    break

        # Get disk usage only
        if hasattr(os, "statvfs"):  # Unix-like systems
            try:
                stat = os.statvfs(disk_usage_path)
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bavail * stat.f_frsize
                used = total - free
            except OSError:
                # Fallback to shutil
                import shutil

                total, used, free = shutil.disk_usage(disk_usage_path)
        else:  # Windows
            import shutil

            total, used, free = shutil.disk_usage(storage.ROOT_DIR)

        return (
            jsonify(
                {
                    "total_space": total,
                    "used_space": used,
                    "free_space": free,
                    "file_count": "counting...",  # Will be updated by full stats
                    "dir_count": "counting...",
                    "content_size": "counting...",
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Error in fast disk stats: {e}")
        return jsonify({"error": f"Fast disk stats error: {str(e)}"}), 500


@app.route("/api/health_check", methods=["GET"])
async def health_check():
    """Simple health check endpoint that doesn't require authentication"""
    return (
        jsonify(
            {
                "status": "ok",
                "platform": os.name,
                "has_statvfs": hasattr(os, "statvfs"),
                "root_dir": ROOT_DIR,
                "timestamp": time.time(),
            }
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Event-loop stall watchdog (diagnostic)
# ---------------------------------------------------------------------------
# A heartbeat coroutine stamps a timestamp every 250 ms on the event loop. A
# plain thread (unaffected by a blocked loop) checks it; if the loop has not
# beat for > _LOOP_STALL_SECS it prints the loop thread's CURRENT stack, i.e.
# the exact line of blocking code. Cause of ERR_HTTP2_PING_FAILED / SSE drops
# and "search stuck 20 s but search_time 0.075 s".
_LOOP_STALL_SECS = 2.0
_loop_beat = {"t": 0.0, "tid": None}
_loop_wd_started = False


async def _loop_heartbeat():
    _loop_beat["tid"] = threading.get_ident()
    while True:
        _loop_beat["t"] = time.monotonic()
        await asyncio.sleep(0.25)


def _loop_watchdog_thread():
    import traceback

    reported_for = 0.0
    while True:
        time.sleep(0.5)
        beat = _loop_beat["t"]
        tid = _loop_beat["tid"]
        if not beat or tid is None:
            continue
        lag = time.monotonic() - beat
        if lag > _LOOP_STALL_SECS and beat != reported_for:
            reported_for = beat
            frame = sys._current_frames().get(tid)
            stack = "".join(traceback.format_stack(frame)) if frame else "(no frame)"
            print(
                f"\n\U0001f6a8 EVENT LOOP BLOCKED for {lag:.1f}s - blocking code:\n{stack}",
                flush=True,
            )


@app.before_serving
async def _start_loop_watchdog():
    global _loop_wd_started
    if _loop_wd_started:
        return
    _loop_wd_started = True
    asyncio.get_running_loop().create_task(_loop_heartbeat())
    threading.Thread(
        target=_loop_watchdog_thread, daemon=True, name="loop-stall-watchdog"
    ).start()


@app.route("/api/search", methods=["GET"])
@login_required
async def search_files():
    """Paginated deep search.

    Query params:
      q      — filename substring (case-insensitive)
      ext    — comma-separated extensions, e.g. "css,js"
      offset — starting row for pagination (default 0)
      limit  — page size (default 500, max 1000)
    """
    query = request.args.get("q", "").strip()
    ext_raw = request.args.get("ext", "").strip().lower()
    offset = max(0, int(request.args.get("offset", 0) or 0))
    limit = min(1000, max(1, int(request.args.get("limit", 500) or 500)))

    ext_filter = (
        [e.strip().lstrip(".") for e in ext_raw.split(",") if e.strip()]
        if ext_raw
        else []
    )

    if not query and not ext_filter:
        return (
            jsonify({"results": [], "query": query, "has_more": False, "offset": 0}),
            200,
        )

    try:
        search_start = time.time()

        # Exact total — single COUNT(*), essentially free on the indexed DB.
        # Only on offset=0 (first page) to avoid repeating it on every scroll page.
        total_count = None
        t_count = 0.0
        if offset == 0 and ENABLE_SEARCH_INDEX:
            _tc = time.time()
            # Blocking SQLite work -> worker thread so the event loop (SSE
            # heartbeats, HTTP/2 pings, other requests) is never stalled.
            c = await asyncio.to_thread(
                search_index_manager.count, query, ext_filter=ext_filter
            )
            t_count = time.time() - _tc
            if c >= 0:  # -1 means index not ready yet
                total_count = c

        _ts = time.time()
        if ENABLE_SEARCH_INDEX:
            results, from_index, has_more = await asyncio.to_thread(
                search_index_manager.search,
                query,
                ext_filter=ext_filter,
                limit=limit,
                offset=offset,
            )
        else:
            results, has_more = await asyncio.to_thread(
                search_index_manager._walk_fallback, query, ext_filter, limit, offset
            )
            from_index = False

        search_time = time.time() - search_start
        t_search = time.time() - _ts
        if search_time > 1.0:
            # Diagnostic (4.52+): which step is slow? count() = files_meta LIKE
            # scan, search() = FTS/LIKE query + one os.stat() per returned row.
            print(
                f"⏱️  Slow search {query!r}: total={search_time:.2f}s "
                f"count={t_count:.2f}s search={t_search:.2f}s "
                f"rows={len(results)} from_index={from_index}",
                flush=True,
            )

        return (
            jsonify(
                {
                    "results": results,
                    "query": query,
                    "ext_filter": ext_filter,
                    "total_found": len(results),
                    "total_count": total_count,  # exact grand total (first page only)
                    "offset": offset,
                    "limit": limit,
                    "has_more": has_more,
                    "search_time": round(search_time, 3),
                    # Diagnostic: per-step seconds (count = total_count query,
                    # search = results query incl. per-row os.stat()).
                    "timing": {
                        "count": round(t_count, 3),
                        "search": round(t_search, 3),
                    },
                    "from_index": from_index,
                    # Diagnostic: None when served from the DB, else why not.
                    "fallback_reason": (
                        None
                        if from_index
                        else (
                            getattr(search_index_manager, "_last_fallback_reason", None)
                            or "search index disabled (ENABLE_SEARCH_INDEX)"
                        )
                    ),
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Search error: {str(e)}")
        return jsonify({"error": f"Search failed: {str(e)}"}), 500


@app.route("/api/speedtest/ping", methods=["GET"])
async def speedtest_ping():
    # Just return OK for latency test
    return jsonify({"ok": True})


@app.route("/api/speedtest/upload", methods=["POST"])
async def speedtest_upload():
    # Receive 25MiB data, measure time server-side if needed
    file = (await request.files).get("data")
    if not file:
        return jsonify({"error": "No data"}), 400
    # Optionally read to memory to simulate disk write
    file.read()
    return jsonify({"ok": True})


@app.route("/api/speedtest/download", methods=["GET"])
async def speedtest_download():
    # Send 5MiB of zero bytes
    size = 5 * 1024 * 1024
    buf = io.BytesIO(b"\x00" * size)
    return await send_file(
        buf,
        mimetype="application/octet-stream",
        as_attachment=True,
        attachment_filename="speedtest.bin",
    )
