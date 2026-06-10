#!/usr/bin/env python3
"""
Development Server for CloudinatorFTP
Runs the Flask development server for testing and debugging.
Enhanced to match ASGI configuration capabilities.
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
#   _BG = True  → SIGINT ignored; use_reloader disabled (Werkzeug's reloader
#                 spawns a watchdog subprocess with its own signal wiring that
#                 would override SIG_IGN — disabling it is the only safe fix)
#   _BG = False → running directly; Ctrl+C and the reloader work as normal
# ---------------------------------------------------------------------------
_BG = os.environ.get("CLOUDINATOR_BG") == "1"
if _BG:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)

# ensure_dirs() is called inside app.py before anything else loads.
from app import app

if __name__ == "__main__":

    # ── Flask / app config ───────────────────────────────────────────────────
    app.config.update(
        MAX_CONTENT_LENGTH=None,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
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
    print("🧪 Starting CloudinatorFTP Development Server...")
    print("⚠️  WARNING: This is for DEVELOPMENT/TESTING only!")
    print("🌐 Server running on http://localhost:5000")
    if _BG:
        print("🔒 Background service mode (managed by manage.sh)")
        print("   • Ctrl+C disabled — use './manage.sh stop' to stop")
        print("   • Auto-reloader disabled (not usable in detached mode)")
    print("🔧 Configuration:")
    print("   • Debug mode: ON  |  Threading: enabled  |  Upload limit: NONE")
    print("   • Auto-reload:", "OFF (BG mode)" if _BG else "ON")
    if not _BG:
        print("📁 Press Ctrl+C to stop the server")
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
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=True,
            threaded=True,
            # Reloader spawns a watchdog subprocess with its own signal wiring.
            # Must be off in BG mode so signal.SIG_IGN cannot be overridden.
            use_reloader=not _BG,
            use_debugger=True,
        )

    except KeyboardInterrupt:
        import threading as _t

        print("\n🛑 Stopping Flask development server…")

        active = [
            t for t in _t.enumerate() if t is not _t.main_thread() and t.is_alive()
        ]
        if active:
            print(f"   ⏳ {len(active)} thread(s) still running:")
            for t in active:
                tag = "[daemon]" if t.daemon else "[active]"
                print(f"      • {t.name} {tag}")

        print("👋 Development server stopped.")
        sys.exit(0)

    except Exception as e:
        print(f"💥 Server error: {e}")
        print("🔍 Check your Flask app and dependencies")
        sys.exit(1)
