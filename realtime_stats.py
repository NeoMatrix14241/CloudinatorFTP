#!/usr/bin/env python3
"""
Real-time Storage Stats Broadcasting
Handles Server-Sent Events for live storage updates.

Quart/asyncio note: broadcast_update() is called from the watchdog
file-monitor's own background thread (see file_monitor.py — it is NOT
asyncio, it's threading.Thread), while event_stream() below runs inside
Hypercorn's event loop. asyncio.Queue is not thread-safe to put() into
directly from a foreign thread, so broadcast pushes are marshalled onto
the loop via loop.call_soon_threadsafe(). The loop reference is captured
lazily the first time a client connects (which always happens on the
event loop thread, inside the async route) — so this file needs no
startup wiring in app.py beyond registering the route itself.
"""

import asyncio
import json
import time
import threading
from typing import Set
from dataclasses import asdict

from quart import Response


class StorageStatsEventManager:
    """Manages real-time storage stats broadcasting to connected clients"""

    def __init__(self):
        self.clients: Set[asyncio.Queue] = set()
        self.lock = threading.Lock()
        self.last_stats = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def add_client(self, client_queue: asyncio.Queue):
        """Add a new client to receive updates. Must be called from the
        event loop thread — captures self.loop for cross-thread broadcasts."""
        with self.lock:
            self.clients.add(client_queue)
            if self.loop is None:
                self.loop = asyncio.get_running_loop()
            print(f"📡 Client connected. Total clients: {len(self.clients)}")

    def remove_client(self, client_queue: asyncio.Queue):
        """Remove a client from updates"""
        with self.lock:
            self.clients.discard(client_queue)
            print(f"📡 Client disconnected. Total clients: {len(self.clients)}")

    def broadcast_update(
        self,
        old_snapshot,
        new_snapshot,
        reconcile_complete: bool = False,
        walk_progress: bool = False,
    ):
        """Broadcast storage stats update to all connected clients.

        Safe to call from any thread (e.g. the watchdog reconcile thread
        in file_monitor.py) — pushes are marshalled onto the event loop.

        Three distinct event kinds (mutually exclusive):
          walk_progress=True,  reconcile_complete=False
            → Fired every ~1s during a reconcile walk.
              Frontend: update stats panel only. Table refresh suppressed
              because _dir_info is still being built.

          walk_progress=False, reconcile_complete=False  (default)
            → Normal watchdog event (file added/deleted/moved/renamed).
              Frontend: update stats panel AND refresh file table.
              _dir_info is kept up-to-date by the watchdog incrementally.

          walk_progress=False, reconcile_complete=True
            → Reconcile walk finished; _dir_info is now fully authoritative.
              Frontend: update stats panel, refresh file table, and re-fetch
              every dir-info cell so folder sizes are correct.
        """
        try:
            # Get fast disk usage stats (without expensive file counting)
            disk_stats = self._get_fast_disk_stats()

            # Prepare the update data with complete storage information
            update_data = {
                "type": "storage_stats_update",
                "timestamp": time.time(),
                "walk_progress": walk_progress,
                "reconcile_complete": reconcile_complete,
                "data": {
                    # File/directory counts from snapshot (instant)
                    "file_count": new_snapshot.file_count,
                    "dir_count": new_snapshot.dir_count,
                    "total_size": new_snapshot.total_size,
                    "content_size": new_snapshot.total_size,  # Alias for compatibility
                    "last_modified": new_snapshot.last_modified,
                    # Disk usage stats (fast disk check)
                    "total_space": disk_stats["total_space"],
                    "free_space": disk_stats["free_space"],
                    "used_space": disk_stats["used_space"],
                    # Change information
                    "changes": {
                        "files_changed": new_snapshot.file_count
                        - (old_snapshot.file_count if old_snapshot else 0),
                        "dirs_changed": new_snapshot.dir_count
                        - (old_snapshot.dir_count if old_snapshot else 0),
                        "size_changed": new_snapshot.total_size
                        - (old_snapshot.total_size if old_snapshot else 0),
                        "content_changed": (
                            old_snapshot.checksum != new_snapshot.checksum
                            if old_snapshot
                            else True
                        ),
                        "mtime_changed": (
                            old_snapshot.last_modified != new_snapshot.last_modified
                            if old_snapshot
                            else True
                        ),
                    },
                },
            }

            self.last_stats = update_data

            # Broadcast to all clients
            with self.lock:
                clients_snapshot = list(self.clients)
                loop = self.loop

            if loop is not None:
                for client_queue in clients_snapshot:
                    loop.call_soon_threadsafe(
                        self._safe_put_nowait, client_queue, update_data
                    )

            print(f"📡 Broadcasted storage update to {len(clients_snapshot)} clients")
            print(
                f"🔍 Update data includes: files={update_data['data']['file_count']}, dirs={update_data['data']['dir_count']}, total_space={update_data['data']['total_space']}, free_space={update_data['data']['free_space']}"
            )

        except Exception as e:
            print(f"❌ Error broadcasting update: {e}")

    @staticmethod
    def _safe_put_nowait(client_queue: asyncio.Queue, update_data: dict):
        """Runs on the event loop thread via call_soon_threadsafe. A full
        queue means a slow/stuck client — drop the update for them rather
        than blocking the loop or the broadcasting thread."""
        try:
            client_queue.put_nowait(update_data)
        except asyncio.QueueFull:
            pass

    def get_last_stats(self):
        """Get the last broadcasted stats"""
        return self.last_stats

    def get_client_count(self):
        """Get the number of connected clients"""
        with self.lock:
            return len(self.clients)

    def _get_fast_disk_stats(self):
        """Get fast disk usage stats without expensive file counting"""
        import os
        import shutil
        from config import ROOT_DIR

        try:
            # Determine the best path for disk usage calculation
            disk_usage_path = ROOT_DIR

            # Special handling for Android/Termux
            if "TERMUX_VERSION" in os.environ or os.path.exists(
                "/data/data/com.termux"
            ):
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
                    total, used, free = shutil.disk_usage(disk_usage_path)
            else:  # Windows
                total, used, free = shutil.disk_usage(ROOT_DIR)

            return {"total_space": total, "used_space": used, "free_space": free}

        except Exception as e:
            print(f"❌ Error getting fast disk stats: {e}")
            return {"total_space": 0, "used_space": 0, "free_space": 0}


# Global event manager
event_manager = StorageStatsEventManager()


async def storage_stats_sse():
    """Server-Sent Events endpoint for real-time storage stats — async
    generator streamed via Hypercorn (HTTP/1.1 chunked, or native DATA
    frames under HTTP/2 and HTTP/3 — no special headers needed for either)."""

    async def event_stream():
        client_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        event_manager.add_client(client_queue)

        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n".encode(
                "utf-8"
            )

            # Always send complete initial stats when client connects
            from file_monitor import get_file_monitor

            file_monitor = get_file_monitor()
            current_snapshot = file_monitor.get_current_snapshot()

            # Provide instant stats - don't wait for slow force_check
            if current_snapshot:
                print("📡 Using cached snapshot for instant SSE response")
                file_count = current_snapshot.file_count
                dir_count = current_snapshot.dir_count
                total_size = current_snapshot.total_size
                last_modified = current_snapshot.last_modified
            else:
                print("📡 No snapshot available, providing instant placeholder stats")
                file_count = 0
                dir_count = 0
                total_size = 0
                last_modified = time.time()

            # Get complete initial storage stats (disk stats are fast)
            disk_stats = event_manager._get_fast_disk_stats()

            initial_stats = {
                "type": "storage_stats_update",
                "timestamp": time.time(),
                "initial": True,
                "data": {
                    "file_count": file_count,
                    "dir_count": dir_count,
                    "total_size": total_size,
                    "content_size": total_size,
                    "last_modified": last_modified,
                    "total_space": disk_stats["total_space"],
                    "free_space": disk_stats["free_space"],
                    "used_space": disk_stats["used_space"],
                    "changes": {
                        "files_changed": 0,
                        "dirs_changed": 0,
                        "size_changed": 0,
                    },
                },
            }

            print(
                f"📡 Sending instant initial storage stats to new client: files={initial_stats['data']['file_count']}, total_space={initial_stats['data']['total_space']}"
            )
            yield f"data: {json.dumps(initial_stats)}\n\n".encode("utf-8")

            # Keep connection alive and send updates
            while True:
                try:
                    data = await asyncio.wait_for(client_queue.get(), timeout=10)
                    yield f"data: {json.dumps(data)}\n\n".encode("utf-8")
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping', 'timestamp': time.time()})}\n\n".encode(
                        "utf-8"
                    )
                except Exception as e:
                    print(f"❌ Error in SSE stream: {e}")
                    break

        finally:
            event_manager.remove_client(client_queue)
            print(f"📡 SSE client cleanup completed")

    response = Response(event_stream(), mimetype="text/event-stream", status=200)

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["X-Accel-Buffering"] = "no"
    # No Content-Length manipulation needed here (unlike the old Waitress
    # version) — Quart never sets Content-Length on an async-generator
    # response body, so it's chunked/streamed by default under Hypercorn
    # on HTTP/1.1, and framed natively under HTTP/2 and HTTP/3.

    return response


def trigger_storage_update(
    old_snapshot,
    new_snapshot,
    reconcile_complete: bool = False,
    walk_progress: bool = False,
):
    """Callback function to be registered with file monitor"""
    event_manager.broadcast_update(
        old_snapshot,
        new_snapshot,
        reconcile_complete=reconcile_complete,
        walk_progress=walk_progress,
    )


def get_event_manager():
    """Get the global event manager"""
    return event_manager
