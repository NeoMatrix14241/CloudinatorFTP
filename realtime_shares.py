#!/usr/bin/env python3
"""
Real-time Share Request Broadcasting
Server-Sent Events for the Manage Shared -> Pending Requests badge, so an
admin sees a new/approved/denied request the instant it happens instead of
waiting on a poll interval or an unfocused-tab timer.

Deliberately mirrors realtime_stats.py's StorageStatsEventManager /
storage_stats_sse pattern (same client-queue broadcast model, same
call_soon_threadsafe cross-thread handoff, same async-generator streaming
response) rather than inventing a second approach that behaves differently
under the same server. See realtime_stats.py's module docstring for why
the thread-to-loop handoff is needed at all.
"""

import asyncio
import json
import time
import threading
from typing import Set

from quart import Response


class ShareEventManager:
    """Manages real-time share-request-count broadcasting to connected admins"""

    def __init__(self):
        self.clients: Set[asyncio.Queue] = set()
        self.lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    def add_client(self, client_queue: asyncio.Queue):
        with self.lock:
            self.clients.add(client_queue)
            if self.loop is None:
                self.loop = asyncio.get_running_loop()
            print(
                f"📡 Share-events client connected. Total clients: {len(self.clients)}"
            )

    def remove_client(self, client_queue: asyncio.Queue):
        with self.lock:
            self.clients.discard(client_queue)
            print(
                f"📡 Share-events client disconnected. Total clients: {len(self.clients)}"
            )

    def broadcast(self, pending_count: int, reason: str):
        """Push the current pending-request count to every connected admin.

        reason ('created' | 'approved' | 'denied') is informational only —
        the client just needs pending_count to redraw the badge/pill, and
        re-fetches the actual request list itself if that tab is open.
        """
        update_data = {
            "type": "share_requests_update",
            "timestamp": time.time(),
            "reason": reason,
            "pending_count": pending_count,
        }
        self._send(
            update_data,
            log_label=f"share-request update ({reason}, pending={pending_count})",
        )

    def broadcast_active_shares_changed(self, reason: str = "expired"):
        """Push a signal that the active-shares list changed (a share was
        auto-revoked for being past its expires_at, wherever that happened —
        the periodic sweep, or a lazy revoke-on-read triggered by an admin
        or a visitor hitting an expired link). The client doesn't need the
        full share data here, just a nudge to refetch — same connection,
        same admin-only stream as the pending-request events, just a
        different event type. This is what makes expiry removal in the
        Manage Shared → Active Shares tab NOT depend on a client-side
        setTimeout ever firing — browsers (especially mobile) can silently
        throttle or suspend those in backgrounded tabs, so the server
        telling the client directly is the only reliable mechanism."""
        update_data = {
            "type": "active_shares_changed",
            "timestamp": time.time(),
            "reason": reason,
        }
        self._send(update_data, log_label=f"active-shares change ({reason})")

    def _send(self, update_data: dict, log_label: str):
        """Safe to call from any thread — see module docstring."""
        with self.lock:
            clients_snapshot = list(self.clients)
            loop = self.loop

        if loop is not None:
            for client_queue in clients_snapshot:
                loop.call_soon_threadsafe(
                    self._safe_put_nowait, client_queue, update_data
                )

        print(f"📡 Broadcasted {log_label} to {len(clients_snapshot)} client(s)")

    @staticmethod
    def _safe_put_nowait(client_queue: asyncio.Queue, update_data: dict):
        try:
            client_queue.put_nowait(update_data)
        except asyncio.QueueFull:
            pass

    def get_client_count(self):
        with self.lock:
            return len(self.clients)


# Global event manager
share_event_manager = ShareEventManager()


async def share_events_sse():
    """Server-Sent Events endpoint for real-time pending-request counts —
    same async-generator streaming approach as storage_stats_sse()."""

    async def event_stream():
        client_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        share_event_manager.add_client(client_queue)

        try:
            # Initial handshake message
            yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n".encode(
                "utf-8"
            )

            # Keep the connection alive and push updates as they're broadcast.
            # A ping every ~15s during quiet periods keeps proxies/load
            # balancers from timing the idle connection out.
            while True:
                try:
                    data = await asyncio.wait_for(client_queue.get(), timeout=15)
                    yield f"data: {json.dumps(data)}\n\n".encode("utf-8")
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping', 'timestamp': time.time()})}\n\n".encode(
                        "utf-8"
                    )
                except Exception as e:
                    print(f"❌ Error in share-events SSE stream: {e}")
                    break

        finally:
            share_event_manager.remove_client(client_queue)
            print("📡 Share-events SSE client cleanup completed")

    response = Response(event_stream(), mimetype="text/event-stream", status=200)

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Accel-Buffering"] = "no"
    # No Content-Length manipulation needed — see realtime_stats.py.
    # No permissive CORS headers here (unlike storage_stats_sse) — this is an
    # authenticated, same-origin admin endpoint; it doesn't need cross-origin
    # credentialed access and shouldn't advertise it.

    return response


def trigger_share_event(pending_count: int, reason: str):
    """Callback used by app.py wherever a request is created, approved, or
    denied — mirrors trigger_storage_update()'s role for the file monitor."""
    share_event_manager.broadcast(pending_count, reason)


def trigger_active_shares_changed(reason: str = "expired"):
    """Callback used by app.py wherever a share gets auto-revoked for being
    past its expires_at — the periodic sweep, or a lazy revoke-on-read."""
    share_event_manager.broadcast_active_shares_changed(reason)


def get_share_event_manager():
    """Get the global share event manager"""
    return share_event_manager
