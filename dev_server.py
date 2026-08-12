#!/usr/bin/env python3
"""
Development Server for CloudinatorFTP
Runs Quart's built-in dev server (Hypercorn under the hood) for testing
and debugging. Plain HTTP by default — no HTTP/2/3 here, TLS setup adds
friction that isn't worth it for fast local iteration; use prod_server.py
if you specifically need to test HTTP/2 or HTTP/3 behaviour locally.
"""

import os
import sys
import signal
from app import get_local_ip

LOCAL_IP = get_local_ip()

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["QUART_ENV"] = "development"
os.environ["QUART_DEBUG"] = "1"

# ---------------------------------------------------------------------------
# Background-service mode  (set by manage.sh launcher)
#   _BG = True  → SIGINT ignored; use_reloader disabled (the reloader spawns
#                 a watchdog subprocess with its own signal wiring that
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

# Start WebDAV / SFTP / FTP protocol servers in background threads.
import protocol_manager

protocol_manager.start_all()

if __name__ == "__main__":

    from config import ROOT_DIR, HOST, PORT, PERMANENT_SESSION_LIFETIME

    # ── Quart app config ─────────────────────────────────────────────────────
    app.config.update(
        MAX_CONTENT_LENGTH=None,  # intentionally unlimited — chunked uploads
        # bypass this anyway (each chunk is well under any reasonable cap),
        # and the person building this app decided unlimited total upload
        # size is fine. Overrides config.py's MAX_CONTENT_LENGTH on purpose.
        PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TESTING=False,
        DEBUG=True,
        TEMPLATES_AUTO_RELOAD=True,
    )

    # ── Startup banner ───────────────────────────────────────────────────────
    print("🧪 Starting CloudinatorFTP Development Server...")
    print("⚠️  WARNING: This is for DEVELOPMENT/TESTING only!")
    print(f"🌐 Server running on http://{LOCAL_IP}:{PORT}")
    if _BG:
        print("🔒 Background service mode (managed by manage.sh)")
        print("   • Ctrl+C disabled — use './manage.sh stop' to stop")
        print("   • Auto-reloader disabled (not usable in detached mode)")
    print("🔧 Configuration:")
    print("   • Debug mode: ON  |  Upload limit: NONE  |  HTTP/1.1 only")
    print("   • Auto-reload:", "OFF (BG mode)" if _BG else "ON")
    if not _BG:
        print("📁 Press Ctrl+C to stop the server")
    print()

    print(f"📋 Storage directory: {ROOT_DIR}")
    print()

    print(f"🌐 Local network:  http://{LOCAL_IP}:{PORT}")
    print(f"🔁 Localhost:      http://localhost:{PORT}")
    print()

    # ── Serve ────────────────────────────────────────────────────────────────
    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=True,
            # The reloader spawns a watchdog subprocess with its own signal
            # wiring. Must be off in BG mode so signal.SIG_IGN cannot be
            # overridden.
            use_reloader=not _BG,
        )

    except KeyboardInterrupt:
        import threading as _t

        print("\n🛑 Stopping development server…")

        # Stop WebDAV / SFTP / FTP / SMB protocol servers cleanly. SMB itself
        # never touches Windows' native file sharing (LanmanServer) — that's
        # a separate, one-time, manually-run setup (smb_setup.py), not
        # something tied to this server's start/stop.
        protocol_manager.stop_all()

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
        print("🔍 Check your Quart app and dependencies")
        sys.exit(1)
