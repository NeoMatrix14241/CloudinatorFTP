"""
hypercorn_ssl_fix.py — Workaround for a real, still-open Hypercorn bug:
https://github.com/pgjones/hypercorn/issues/202

Since Python 3.11, asyncio's SSL transport waits up to a default 30
SECONDS for a clean TLS close_notify handshake whenever a connection is
closed (this is new — it didn't exist on 3.8/3.9/3.10). If the peer
already forcibly reset the connection instead of closing it gracefully —
extremely common: a browser cancelling a download does exactly this — no
close_notify is ever coming, so that wait runs the FULL 30 seconds before
giving up with a TimeoutError.

Hypercorn's own TCPServer._close() (hypercorn/asyncio/tcp_server.py)
already catches ConnectionResetError/BrokenPipeError/etc. for the
"already closed" case, but does NOT catch the resulting TimeoutError —
so it escapes as an "Unhandled exception in client_connected_cb". Worse,
that 30-second wait itself is real dead time on that connection's cleanup
task; if a client tries to reuse the same (now zombied) connection for
its next request, the site can appear to hang until the client gives up
and opens a fresh one. Verified directly against the installed Hypercorn
0.18.0 source — this isn't a guess.

Confirmed present on Hypercorn 0.16.0 through at least 0.18.0 (latest as
of writing), unresolved upstream — there's an open PR (#342) but no
released fix. This module patches TCPServer._close() in-process:
  1. Actually catches TimeoutError (fixes the unhandled-exception spam).
  2. Caps the close-wait at SHUTDOWN_TIMEOUT_SECONDS instead of asyncio's
     30s default (fixes the real hang, not just the noisy traceback).

Call apply() once, as early as possible, in EVERY process that runs a
Hypercorn server — the main app (prod_server.py) and WebDAV
(webdav_server.py) are separate processes/Hypercorn instances, so each
needs its own call. Safe to call more than once (no-ops after the first).

Defensive by design: if Hypercorn's internals change in some future
version and TCPServer._close no longer has the shape this patch expects,
apply() logs a warning and leaves Hypercorn's original (buggy but
functional) behavior in place rather than crashing the server. Re-check
this patch against Hypercorn's source after any Hypercorn upgrade — if
they ship their own fix for #202, this can be removed.
"""

import asyncio
import logging

_PATCHED = False

# How long to actually wait for a graceful SSL close before giving up.
# Hypercorn/asyncio's own default is 30s — this is deliberately much
# shorter: a peer that already reset the connection is never coming back
# with a close_notify, so there's nothing to gain from waiting longer.
# A couple seconds still gives a genuinely-slow-but-alive peer a real
# chance to complete a clean shutdown.
SHUTDOWN_TIMEOUT_SECONDS = 2.0


def apply() -> bool:
    """Patch hypercorn.asyncio.tcp_server.TCPServer._close(). Returns True
    if the patch was applied (or already had been), False if it couldn't
    be (logged as a warning, not fatal — server still runs, just with
    Hypercorn's original 30s-hang behavior)."""
    global _PATCHED
    if _PATCHED:
        return True

    log = logging.getLogger(__name__)

    try:
        from hypercorn.asyncio.tcp_server import TCPServer

        async def _patched_close(self) -> None:
            try:
                self.writer.write_eof()
            except (NotImplementedError, OSError, RuntimeError):
                pass  # Likely SSL connection

            try:
                self.writer.close()
                # The actual fix: bound the wait instead of asyncio's
                # own 30s ssl_shutdown_timeout default.
                await asyncio.wait_for(
                    self.writer.wait_closed(), timeout=SHUTDOWN_TIMEOUT_SECONDS
                )
            except (
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError,
                RuntimeError,
                asyncio.CancelledError,
                TimeoutError,  # == asyncio.TimeoutError on 3.11+ — the
                # exact exception Hypercorn's original _close() fails to
                # catch (see this module's docstring / hypercorn#202).
            ):
                pass  # Already closed, or peer gone — nothing more to do
            finally:
                await self.idle_task.stop()

        TCPServer._close = _patched_close
        _PATCHED = True
        log.info(
            "hypercorn_ssl_fix: patched TCPServer._close() — "
            f"30s SSL-shutdown hang capped to {SHUTDOWN_TIMEOUT_SECONDS}s, "
            "TimeoutError now handled (see hypercorn#202)."
        )
        return True

    except Exception as e:
        log.warning(
            f"hypercorn_ssl_fix: could not apply patch ({e!r}) — Hypercorn's "
            "original behavior remains in effect (a client abruptly resetting "
            "a connection, e.g. cancelling a download, can cause a ~30s stall "
            "and an unhandled-exception log entry for that connection's "
            "cleanup). Not fatal — check whether Hypercorn's internals "
            "changed if this appears after an upgrade."
        )
        return False
