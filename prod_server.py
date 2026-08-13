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
1.3 — there's no cleartext QUIC.

Certificate source, in priority order:
  1. Tailscale — if the `tailscale` CLI is found, the machine is logged
     into a tailnet with MagicDNS + HTTPS Certificates enabled, `tailscale
     cert` is used to issue/renew a REAL, publicly-trusted Let's Encrypt
     cert for this device's `*.ts.net` name. No browser warning, no
     per-client cert import, but only reachable via the tailnet (Tailscale
     installed + logged in on the client) at https://<device>.<tailnet>.ts.net:PORT/.
  2. ssl_cert.py fallback — if Tailscale isn't installed/logged in, or
     HTTPS Certificates isn't enabled for the tailnet, or the `tailscale
     cert` call fails for any reason (e.g. no internet), falls back to the
     self-signed CA cert (db/webdav.crt + db/webdav.key) — the same one
     WebDAV HTTPS already uses. Reachable at https://HOST:PORT/ via LAN IP
     or localhost, but browsers show a warning until that cert is imported
     as a trusted root — see ssl_cert.py's module docstring for per-OS
     import steps.

Both paths can be used at once (Tailscale cert is what's actually bound to
Hypercorn, but the self-signed one is still generated/available for
LAN-only clients that aren't on the tailnet — see ssl_cert.py directly).
"""

import os
import sys
import json
import shutil
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


# ---------------------------------------------------------------------------
# Tailscale certificate support
# ---------------------------------------------------------------------------
# If this machine is on a tailnet with MagicDNS + HTTPS Certificates
# enabled, `tailscale cert` gets us a real Let's Encrypt cert for our
# *.ts.net name — no self-signed warning, no per-client cert import.
# Falls back silently to ssl_cert.py's self-signed cert if anything here
# isn't available (Tailscale not installed, not logged in, HTTPS not
# enabled for the tailnet, no internet, etc.) — this is best-effort, never
# a hard requirement to start the server.


def _find_tailscale_exe() -> str | None:
    """Locate the tailscale CLI. shutil.which() covers the common case
    (it's on PATH on Linux/macOS and most modern Windows installs); falls
    back to Tailscale's default Windows install location since the Windows
    GUI client doesn't always add itself to PATH."""
    exe = shutil.which("tailscale")
    if exe:
        return exe
    if sys.platform == "win32":
        default = r"C:\Program Files\Tailscale\tailscale.exe"
        if os.path.exists(default):
            return default
    return None


async def _get_tailscale_dns_name(ts_exe: str) -> str | None:
    """Return this machine's MagicDNS name (e.g. 'myserver.tailnet.ts.net'),
    or None if Tailscale isn't running/logged in."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ts_exe,
            "status",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return None
        data = json.loads(stdout)
        dns_name = data.get("Self", {}).get("DNSName", "").rstrip(".")
        return dns_name or None
    except Exception:
        return None


async def _get_tailscale_cert(
    ts_exe: str, dns_name: str, db_dir: str
) -> tuple[str, str] | None:
    """Issue or renew a real cert for `dns_name` via `tailscale cert`,
    writing it into db_dir alongside the self-signed fallback. Returns
    (cert_path, key_path) on success, None on any failure — caller falls
    back to ssl_cert.py's self-signed cert."""
    cert_path = os.path.join(db_dir, "tailscale.crt")
    key_path = os.path.join(db_dir, "tailscale.key")
    try:
        proc = await asyncio.create_subprocess_exec(
            ts_exe,
            "cert",
            "--cert-file",
            cert_path,
            "--key-file",
            key_path,
            dns_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            print(
                f"⚠️  tailscale cert failed: {stderr.decode(errors='replace').strip()}"
            )
            return None
        if not (os.path.exists(cert_path) and os.path.exists(key_path)):
            return None
        return cert_path, key_path
    except Exception as e:
        print(f"⚠️  tailscale cert error: {e}")
        return None


# Re-issue every 12h while the server stays up — tailscale certs are
# short-lived (Let's Encrypt, ~90 days) but nothing renews them
# automatically except re-running `tailscale cert`. A restart alone only
# covers renewal if the server happens to restart before expiry; a
# long-running process needs this loop too.
_TAILSCALE_RENEW_INTERVAL = 12 * 3600


async def _tailscale_renew_loop(ts_exe: str, dns_name: str, db_dir: str):
    while True:
        await asyncio.sleep(_TAILSCALE_RENEW_INTERVAL)
        result = await _get_tailscale_cert(ts_exe, dns_name, db_dir)
        if result:
            print("🔄 Tailscale certificate renewed.")
        else:
            print(
                f"⚠️  Tailscale certificate renewal failed — will retry in "
                f"{_TAILSCALE_RENEW_INTERVAL // 3600}h."
            )


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

    # ── Cert selection: Tailscale first, self-signed fallback ─────────────
    cert_path = key_path = None
    tailscale_exe = _find_tailscale_exe()
    tailscale_dns_name = None
    if tailscale_exe:
        tailscale_dns_name = await _get_tailscale_dns_name(tailscale_exe)
        if tailscale_dns_name:
            result = await _get_tailscale_cert(
                tailscale_exe, tailscale_dns_name, db_dir
            )
            if result:
                cert_path, key_path = result

    using_tailscale = cert_path is not None
    if not using_tailscale:
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
    hyper_cfg.alpn_protocols = ["h2"]  # HTTP/3 negotiates over
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
    if using_tailscale:
        print(f"🔒 Tailscale HTTPS:  https://{tailscale_dns_name}:{PORT}")
        print("   Real, publicly-trusted cert — no browser warning, no")
        print("   per-client import needed. Reachable from any device on")
        print("   this tailnet with Tailscale installed and logged in.")
        print()
        print(f"🌐 Local network:  https://{LOCAL_IP}:{PORT}  (self-signed cert")
        print("   still generated for LAN clients not on the tailnet — see")
        print("   ssl_cert.py for per-OS trust-import steps if you use this.)")
    else:
        print(f"🌐 Local network:  https://{LOCAL_IP}:{PORT}")
        print(f"🔁 Localhost:      https://localhost:{PORT}")
        print()
        print("⚠️  First connection from a new client will show a self-signed")
        print(f"   certificate warning until {cert_path} is imported as a")
        print("   trusted root — see ssl_cert.py's module docstring for the")
        print("   per-OS steps (same cert/steps WebDAV HTTPS already uses).")
        if tailscale_exe and not tailscale_dns_name:
            print()
            print("💡 Tailscale CLI found but not logged in / no MagicDNS name —")
            print("   run `tailscale up` and enable MagicDNS + HTTPS Certificates")
            print("   in the admin console to get a real trusted cert instead.")
        elif not tailscale_exe:
            print()
            print("💡 Install Tailscale for a real trusted cert with zero")
            print("   per-client import: https://tailscale.com/download")
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

    renew_task = None
    if using_tailscale:
        renew_task = asyncio.create_task(
            _tailscale_renew_loop(tailscale_exe, tailscale_dns_name, db_dir)
        )

    try:
        await serve(
            app,
            hyper_cfg,
            shutdown_trigger=_shutdown_trigger if not _BG else None,
        )
    finally:
        if renew_task:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass

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
