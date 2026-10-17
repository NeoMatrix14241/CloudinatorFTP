"""
routes/admin.py - admin cache routes: /admin/clear_media_preview and /admin/rebuild_cache(+status)
(Phase 6 of the split, CLAUDE.md 4.74).

Moved verbatim from app.py. The HLS / image cache helpers come from their own route modules.
Gets shared objects via `from core import ...`.
"""

from core import app, login_required

from quart import jsonify
import os
import shutil
import asyncio
import threading
import time
from auth import current_user, get_role
from routes.hls import _hls_cache_root, _hls_read_status
from routes.image_preview import (
    _img_cache_root,
    _img_conv_events,
    _img_events_mutex,
)


@app.route("/admin/clear_media_preview", methods=["POST"])
@login_required
async def clear_media_preview():
    """Thin async wrapper — see _clear_media_preview_sync. Walking/scanning
    the HLS and image cache directories is synchronous filesystem work;
    same reasoning as archive_preview's wrapper above."""
    return await asyncio.to_thread(_clear_media_preview_sync)


def _clear_media_preview_sync():
    """Admin endpoint to clear HLS transcode and image preview caches."""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        hls_dirs_removed = 0
        hls_dirs_skipped = 0
        hls_bytes_freed = 0

        img_files_removed = 0
        img_files_skipped = 0
        img_bytes_freed = 0

        # ── 1. Clear HLS transcode cache ──────────────────────────────────────
        # Each subdirectory of hls_root is one transcode job (named by cache key).
        # Skip any whose .status.json reports "processing" — an ffmpeg worker is
        # actively writing segments into that directory right now.
        hls_root = _hls_cache_root()
        if os.path.isdir(hls_root):
            for entry in os.scandir(hls_root):
                if not entry.is_dir():
                    continue
                cache_key = entry.name
                if _hls_read_status(cache_key).get("status") == "processing":
                    hls_dirs_skipped += 1
                    print(f"⏭️  Skipping active HLS transcode: {cache_key}")
                    continue
                try:
                    dir_size = sum(
                        os.path.getsize(os.path.join(root, f))
                        for root, _, files in os.walk(entry.path)
                        for f in files
                    )
                    shutil.rmtree(entry.path)
                    hls_dirs_removed += 1
                    hls_bytes_freed += dir_size
                except Exception as ex:
                    print(f"⚠️  Failed to remove HLS cache dir {entry.path}: {ex}")

        # ── 2. Clear image preview cache ──────────────────────────────────────
        # Flat files in img_root: {cache_key}.webp / .jpg / .png / .meta.json
        # Snapshot active keys first (under the mutex used by the converter) so
        # we never delete a file whose conversion thread is still writing to it.
        with _img_events_mutex:
            active_img_keys = set(_img_conv_events.keys())

        img_root = _img_cache_root()
        if os.path.isdir(img_root):
            for entry in os.scandir(img_root):
                if not entry.is_file():
                    continue
                # cache_key is always the first 32-char hex segment before any '.'
                cache_key = entry.name.split(".")[0]
                if cache_key in active_img_keys:
                    img_files_skipped += 1
                    print(f"⏭️  Skipping active image conversion: {cache_key}")
                    continue
                try:
                    img_bytes_freed += entry.stat().st_size
                    os.remove(entry.path)
                    img_files_removed += 1
                except Exception as ex:
                    print(f"⚠️  Failed to remove image cache file {entry.path}: {ex}")

        total_bytes = hls_bytes_freed + img_bytes_freed
        total_mb = total_bytes / (1024 * 1024)
        skipped_total = hls_dirs_skipped + img_files_skipped

        print(
            f"🧹 Media preview cache cleared: "
            f"{hls_dirs_removed} HLS dir(s), {img_files_removed} image file(s) removed "
            f"({total_mb:.1f} MB freed). "
            f"Skipped: {hls_dirs_skipped} active HLS, {img_files_skipped} active image."
        )

        skipped_note = (
            f" Skipped {skipped_total} active job(s)." if skipped_total > 0 else ""
        )
        return (
            jsonify(
                {
                    "success": True,
                    "message": (
                        f"Media preview cache cleared: "
                        f"{hls_dirs_removed} HLS transcode(s) and "
                        f"{img_files_removed} image preview(s) removed "
                        f"({total_mb:.1f} MB freed).{skipped_note}"
                    ),
                    "hls_dirs_removed": hls_dirs_removed,
                    "hls_dirs_skipped": hls_dirs_skipped,
                    "img_files_removed": img_files_removed,
                    "img_files_skipped": img_files_skipped,
                    "bytes_freed": total_bytes,
                }
            ),
            200,
        )

    except Exception as e:
        print(f"❌ Error clearing media preview cache: {e}")
        return jsonify({"error": str(e)}), 500


# 4.63: Rebuild Cache runs in the background. The walk of a big tree on the HDD
# takes minutes; running it inside the request made a reverse proxy / CDN give up
# first (HTTP 524 after ~100 s with an HTML body), and the browser then failed
# with "Unexpected token '<'" while the server finished the rebuild anyway.
_rebuild_state = {
    "state": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "message": "",
    "error": "",
}
_rebuild_state_lock = threading.Lock()


def _rebuild_cache_worker():
    """Delete both JSON caches, force a ground-truth walk, audit the file index,
    then record the outcome in _rebuild_state (polled by the status route)."""
    state, message, error = "error", "", ""
    try:
        import os
        from file_monitor import get_file_monitor, CACHE_FILE
        from file_index import file_index_manager, FILE_INDEX_PATH

        # Delete storage_index.json
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print(f"🗑️ Cache file deleted: {CACHE_FILE}")
        else:
            print("ℹ️ No cache file found — nothing to delete")

        # Delete file_index.json
        if os.path.exists(FILE_INDEX_PATH):
            os.remove(FILE_INDEX_PATH)
            file_index_manager.clear()
            print(f"🗑️ File index deleted: {FILE_INDEX_PATH}")
        else:
            print("ℹ️ No file index found — nothing to delete")

        monitor = get_file_monitor()
        print("🚶 Rebuilding cache from scratch...")
        # force=True: an admin rebuild must be able to accept a genuinely
        # empty tree (the automatic walks reject a suspect-empty result once).
        applied = monitor._reconcile(force=True)

        # 4.59: audit the freshly built file index against the disk
        # (read-only, repair=False). Right after a walk this should report 0
        # drifted; anything else means files changed during the rebuild.
        audit = None
        try:
            audit = file_index_manager.verify_all(repair=False)
        except Exception as _ve:
            print(f"⚠️ file index verify failed: {_ve}")

        if not applied:
            error = (
                "Rebuild walk did not complete (root unreadable?) — "
                "previous index kept; see the server log"
            )
        else:
            from realtime_stats import trigger_storage_update

            trigger_storage_update(None, monitor.get_current_snapshot())
            fi_stats = file_index_manager.get_stats()
            message = (
                f"Cache cleared and rebuilt: {monitor._file_count:,} files, "
                f"{monitor._dir_count:,} dirs, {len(monitor._dir_info):,} folders indexed. "
                f'File index: {fi_stats["indexed_folders"]:,} large folder(s) indexed '
                f'({fi_stats["total_entries"]:,} entries, threshold={fi_stats["threshold"]})'
                + (
                    f'. Verified {audit["checked"]:,} indexed folder(s) against disk: '
                    f'{audit["drifted"]:,} drifted, {audit["unreadable"]:,} unreadable'
                    if audit
                    else ""
                )
            )
            state = "done"
    except Exception as e:
        print(f"❌ Error during cache cleanup: {e}")
        error = str(e) or e.__class__.__name__
    finally:
        with _rebuild_state_lock:
            _rebuild_state.update(
                state=state,
                finished_at=time.time(),
                message=message,
                error=error,
            )


@app.route("/admin/rebuild_cache", methods=["POST"])
@login_required
async def admin_rebuild_cache():
    """Start a cache rebuild in the background (returns at once; poll
    /admin/rebuild_cache/status for the outcome)."""
    try:
        role = get_role(current_user())
        if role != "readwrite":
            return jsonify({"error": "Permission denied"}), 403

        with _rebuild_state_lock:
            if _rebuild_state["state"] == "running":
                return (
                    jsonify(
                        {
                            "error": "A cache rebuild is already running",
                            "running": True,
                            "started_at": _rebuild_state["started_at"],
                            "elapsed": round(
                                time.time() - _rebuild_state["started_at"], 1
                            ),
                        }
                    ),
                    409,
                )
            _rebuild_state.update(
                state="running",
                started_at=time.time(),
                finished_at=None,
                message="",
                error="",
            )
        threading.Thread(
            target=_rebuild_cache_worker, name="rebuild-cache", daemon=True
        ).start()
        return (
            jsonify(
                {
                    "success": True,
                    "started": True,
                    "message": "Cache rebuild started in the background",
                }
            ),
            202,
        )

    except Exception as e:
        print(f"❌ Error starting cache rebuild: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/admin/rebuild_cache/status", methods=["GET"])
@login_required
async def admin_rebuild_cache_status():
    """Outcome of the last/current Rebuild Cache: state idle|running|done|error."""
    role = get_role(current_user())
    if role != "readwrite":
        return jsonify({"error": "Permission denied"}), 403
    with _rebuild_state_lock:
        snap = dict(_rebuild_state)
    # 4.66: seconds the running rebuild has been going, measured on the server,
    # so a page opened/refreshed mid-rebuild can resume the timer where it is.
    if snap.get("state") == "running" and snap.get("started_at"):
        snap["elapsed"] = round(time.time() - snap["started_at"], 1)
    return jsonify(snap), 200
