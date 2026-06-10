#!/usr/bin/env python3
"""
Production Server for CloudinatorFTP
Runs the Waitress WSGI server for production/live use.
"""

import os
import sys
import signal
import socket
from datetime import timedelta


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["FLASK_ENV"] = "development"

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

if __name__ == "__main__":

    # ── Two-stage Ctrl+C handler (direct-run only) ───────────────────────────
    # 1st Ctrl+C → graceful shutdown with thread report
    # 2nd Ctrl+C → os._exit(0) immediately (no more waiting)
    if not _BG:
        _stopping = False

        def _sigint_handler(sig, frame):
            global _stopping
            if _stopping:
                print("\n⚡ Force quitting — terminating immediately…", flush=True)
                os._exit(0)
            _stopping = True
            print(
                "\n🛑 Interrupt received — shutting down…  (Ctrl+C again to force quit)",
                flush=True,
            )
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _sigint_handler)

    # ── Flask / app config ───────────────────────────────────────────────────
    app.config.update(
        MAX_CONTENT_LENGTH=None,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TESTING=False,
        DEBUG=True,
        THREADED=True,
        PROPAGATE_EXCEPTIONS=True,
        PRESERVE_CONTEXT_ON_EXCEPTION=None,
        TEMPLATES_AUTO_RELOAD=True,
        EXPLAIN_TEMPLATE_LOADING=False,
    )

    # ── Startup banner ───────────────────────────────────────────────────────
    print("🧪 Starting CloudinatorFTP Production Server...")
    print("🌐 Server running on http://localhost:5000")
    if _BG:
        print("🔒 Background service mode (managed by manage.sh)")
        print("   • Ctrl+C disabled — use './manage.sh stop' to stop")
    print("🔧 Configuration:")
    print("   • Threads: 24  |  Connection limit: 500  |  Channel timeout: 30s")
    print("   • Upload size limit: NONE  |  SSE streaming: enabled")
    if not _BG:
        print("📁 Press Ctrl+C to stop  (Ctrl+C twice to force quit)")
    print()

    from config import ROOT_DIR

    print(f"📋 Storage directory: {ROOT_DIR}")
    print()

    LOCAL_IP = get_local_ip()
    print(f"🌐 Local network:  http://{LOCAL_IP}:5000")
    print(f"🔁 Localhost:      http://localhost:5000")
    print()

    # ── Serve ────────────────────────────────────────────────────────────────
    try:
        from waitress import serve

        print("🚀 Starting Waitress server…")
        print(
            "✅ HTTP keep-alive enabled — TCP connections reused for multiple requests"
        )
        print("✅ SSE streaming enabled — real-time updates work")
        serve(
            app,
            host="0.0.0.0",
            port=5000,
            threads=24,
            connection_limit=500,
            channel_timeout=30,
            cleanup_interval=5,
            asyncore_use_poll=True,
        )

    except ImportError:
        print("⚠️  Waitress not installed — run: pip install waitress")
        print("⚠️  Falling back to Flask dev server (16 MB upload limit applies)")
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=True,
            threaded=True,
            use_reloader=not _BG,
            use_debugger=True,
        )

    except KeyboardInterrupt:
        import threading as _t, time as _time

        print("\n🛑 Stopping Waitress server…")

        # Brief pause — lets asyncore close the listening socket
        _time.sleep(0.3)

        active = [
            t for t in _t.enumerate() if t is not _t.main_thread() and t.is_alive()
        ]
        if active:
            print(f"   ⏳ {len(active)} thread(s) still running:")
            for t in active:
                tag = "[daemon]" if t.daemon else "[active]"
                print(f"      • {t.name} {tag}")
            print("   Waiting up to 3s for threads to finish…")

            deadline = _time.time() + 3
            while _time.time() < deadline:
                pending = [
                    t
                    for t in _t.enumerate()
                    if t is not _t.main_thread() and t.is_alive() and not t.daemon
                ]
                if not pending:
                    break
                _time.sleep(0.2)

            stuck = [
                t
                for t in _t.enumerate()
                if t is not _t.main_thread() and t.is_alive() and not t.daemon
            ]
            if stuck:
                print(f"   ⚠️  {len(stuck)} thread(s) did not finish — forcing exit")
                os._exit(0)

        print("👋 Production server stopped.")
        sys.exit(0)

    except Exception as e:
        print(f"💥 Server error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
