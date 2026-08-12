#!/usr/bin/env python3
"""
Production Server for CloudinatorFTP
Runs Hypercorn (ASGI) for production/live use — HTTP/1.1, HTTP/2, and
HTTP/3 (QUIC) all served from this one process.

Concurrency model change from the old Waitress setup: Waitress handled
~1024 concurrent connections with a thread pool (threads=1024). Hypercorn's
asyncio worker handles concurrency via the event loop instead — connections
aren't backed by OS threads at all, so there's no equivalent "threads="
knob to set. keep_alive_timeout below is the actual carried-over setting
(was channel_timeout=30 under Waitress).

TLS is now mandatory, not optional: HTTP/2 works over plaintext (h2c) in
theory but no browser implements it, and HTTP/3/QUIC only exists over TLS
1.3 — there's no cleartext QUIC. This reuses ssl_cert.py's self-signed CA
cert (db/webdav.crt + db/webdav.key) — the same one WebDAV HTTPS already
uses — rather than minting a second one; import that one cert on each
client and both WebDAV and the main app trust it.

Practical effect: the app is now only reachable at https://HOST:PORT/,
not http://. Browsers will show a self-signed-certificate warning until
that cert is imported as a trusted root — see ssl_cert.py's module
docstring for the per-OS import steps (same steps already used for WebDAV).
"""

import os
import sys
import signal
import asyncio
import logging

# Lower the GIL switch interval (default 0.005s) BEFORE anything else runs.
# `from app import app` below triggers file_monitor.init_file_monitor() at
# IMPORT time, which spawns a background thread that walks the whole storage
# tree. Under Hypercorn there's a single thread running the entire asyncio
# event loop, so pure-Python work in that walk thread (dict bookkeeping,
# bubbling counts up every ancestor folder, etc. — not just the os.stat()
# syscalls) can hold the GIL for a full 5ms bytecode-check window at a time
# and starve the event loop of any turn at all. This doesn't replace the
# explicit time.sleep(0) yields added inside file_monitor.py's walk loop —
# those are the real fix — but it's a cheap global backstop for the
# pure-Python stretches *between* those yields. Must be set before the
# `from app import app` import below, since that import is what starts the
# walk thread's 30s countdown.
sys.setswitchinterval(0.001)

from app import get_local_ip

LOCAL_IP = get_local_ip()


def _build_hypercorn_logger(name: str) -> logging.Logger:
    """Hypercorn's own default error-log formatter (used whenever
    Config.errorlog is left at its default "-") includes %(process)d.
    On Python 3.14, record.process comes back None in this exact code
    path — a Python 3.14 logging-module behavior change, not a bug in
    this app — which crashes logging.Formatter's %-formatting with
    "TypeError: %d format: a real number is required, not NoneType"
    every single time Hypercorn tries to log anything, including its own
    startup banner.

    Hypercorn's _create_logger() has an early return for an already-built
    logging.Logger object (isinstance(target, logging.Logger): return
    target) — passing one in, instead of the string "-", makes Hypercorn
    skip its own crashing formatter construction entirely rather than
    hitting this bug and needing us to catch/suppress the resulting
    per-request logging errors.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

os.environ["PYTHONUNBUFFERED"] = "1"

# ---------------------------------------------------------------------------
# Background-service mode  (set by manage.sh launcher)
#   _BG = True  → SIGINT ignored, manage.sh stop/taskkill handles shutdown
#   _BG = False → running directly; two-stage Ctrl+C handler is installed
# ---------------------------------------------------------------------------
_BG = os.environ.get("CLOUDINATOR_BG") == "1"
if _BG:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)

# ensure_dirs() is called inside app.py before anything else loads.
from app import app

# Start WebDAV / SFTP / FTP / SMB protocol servers in background threads.
import protocol_manager

protocol_manager.start_all()


async def _run():
    from config import ROOT_DIR, HOST, PORT, PERMANENT_SESSION_LIFETIME
    from paths import get_db_dir
    import ssl_cert
    from hypercorn.config import Config as HyperConfig
    from hypercorn.asyncio import serve

    # ── Quart app config ────────────────────────────────────────────────────
    app.config.update(
        MAX_CONTENT_LENGTH=None,  # intentionally unlimited — chunked uploads
        # bypass this anyway (each chunk is well under any reasonable cap),
        # and the person building this app decided unlimited total upload
        # size is fine. Overrides config.py's MAX_CONTENT_LENGTH on purpose.
        PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TESTING=False,
        DEBUG=False,
        TEMPLATES_AUTO_RELOAD=False,
    )

    db_dir = get_db_dir(create=True)
    cert_path, key_path = ssl_cert.get_cert_paths(db_dir)

    hyper_cfg = HyperConfig()
    hyper_cfg.bind = [f"{HOST}:{PORT}"]
    hyper_cfg.quic_bind = [
        f"{HOST}:{PORT}"
    ]  # HTTP/3 — same port number, UDP instead of TCP
    hyper_cfg.certfile = cert_path
    hyper_cfg.keyfile = key_path
    hyper_cfg.errorlog = _build_hypercorn_logger(
        "hypercorn.error"
    )  # see _build_hypercorn_logger's docstring
    hyper_cfg.alpn_protocols = ["h2", "http/1.1"]  # HTTP/3 negotiates over
    # QUIC/UDP separately (via Alt-Svc, which Hypercorn adds automatically
    # once quic_bind is set) — "h3" is not a valid ALPN token for the TCP/TLS
    # listener and breaks its handshake if included here.
    hyper_cfg.keep_alive_timeout = 30  # carried over from Waitress's channel_timeout=30
    # NOTE: keep_alive_max_requests intentionally left at Hypercorn's default
    # (1000). Setting it to 0 does NOT mean unlimited — Hypercorn's h2
    # protocol closes the connection once keep_alive_requests > max, so 0
    # closes after the very first request on every HTTP/2 connection (found
    # this the hard way: every request GOAWAY'd immediately with no
    # exception logged anywhere, HTTP/1.1 was unaffected since it doesn't
    # enforce this the same way). 1000 requests per connection before a
    # forced reconnect is already generous; raise it further if needed.
    # workers MUST stay 1: bulk_zip_progress/bulk_zip_cancelled, the SSE
    # client sets in realtime_stats.py/realtime_shares.py, ChunkTracker, and
    # the watchdog file_monitor's in-memory snapshot are all plain Python
    # objects living in this one process's memory. Hypercorn workers are
    # separate OS processes with separate memory — a second worker would
    # silently not share any of that state (uploads assigned to worker A
    # would look incomplete to worker B, SSE clients on worker A would
    # never see events broadcast from worker B, etc). Scaling beyond one
    # process would need that state moved into SQLite/Redis first.
    hyper_cfg.workers = 1

    # ── Startup banner ───────────────────────────────────────────────────────
    print("🚀 Starting CloudinatorFTP Production Server (Hypercorn)...")
    print(f"🌐 Server running on https://{LOCAL_IP}:{PORT}")
    if _BG:
        print("🔒 Background service mode (managed by manage.sh)")
        print("   • Ctrl+C disabled — use './manage.sh stop' to stop")
    print("🔧 Configuration:")
    print("   • HTTP/1.1 + HTTP/2 + HTTP/3 (QUIC)  |  Upload size limit: NONE")
    print(
        "   • SSE streaming: enabled  |  Workers: 1 (see comments in this file for why)"
    )
    if not _BG:
        print("📁 Press Ctrl+C to stop  (Ctrl+C twice to force quit)")
    print()
    print(f"📋 Storage directory: {ROOT_DIR}")
    print()
    print(f"🌐 Local network:  https://{LOCAL_IP}:{PORT}")
    print(f"🔁 Localhost:      https://localhost:{PORT}")
    print()
    print("⚠️  First connection from a new client will show a self-signed")
    print(f"   certificate warning until {cert_path} is imported as a")
    print("   trusted root — see ssl_cert.py's module docstring for the")
    print("   per-OS steps (same cert/steps WebDAV HTTPS already uses).")
    print()

    # ── Graceful shutdown wiring ─────────────────────────────────────────────
    shutdown_event = asyncio.Event()

    if not _BG:
        _stop_count = 0

        def _sigint_handler(*_args):
            nonlocal _stop_count
            _stop_count += 1
            if _stop_count == 1:
                print(
                    "\n🛑 Interrupt received — shutting down…  (Ctrl+C again to force quit)",
                    flush=True,
                )
                shutdown_event.set()
            else:
                print("\n⚡ Force quitting — terminating immediately…", flush=True)
                os._exit(0)

        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, _sigint_handler)
        except NotImplementedError:
            # Windows: asyncio's default event loop (ProactorEventLoop) never
            # implements add_signal_handler — it's Unix-only, always has been.
            # signal.signal() still works fine here: Python delivers signals
            # on the main thread between bytecode instructions, the event
            # loop is also running on the main thread, so calling
            # shutdown_event.set() directly from the handler is safe with no
            # cross-thread marshalling needed (unlike webdav_server.py's or
            # realtime_stats.py's cross-thread cases, which genuinely do need
            # call_soon_threadsafe because they're signaled from a different
            # OS thread than the one running the loop).
            signal.signal(signal.SIGINT, _sigint_handler)

    async def _shutdown_trigger():
        await shutdown_event.wait()

    try:
        await serve(
            app,
            hyper_cfg,
            shutdown_trigger=_shutdown_trigger if not _BG else None,
        )
    finally:
        print("\n🛑 Stopping protocol servers…")
        protocol_manager.stop_all()

        active = [
            t
            for t in __import__("threading").enumerate()
            if t is not __import__("threading").main_thread() and t.is_alive()
        ]
        if active:
            print(f"   ⏳ {len(active)} thread(s) still running:")
            for t in active:
                tag = "[daemon]" if t.daemon else "[active]"
                print(f"      • {t.name} {tag}")

        print("👋 Production server stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        # Only reachable in _BG mode (SIGINT is SIG_IGN'd there anyway) or
        # if the signal fires before add_signal_handler runs — asyncio.run's
        # own teardown already closed the loop by this point.
        sys.exit(0)
    except Exception as e:
        print(f"💥 Server error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
