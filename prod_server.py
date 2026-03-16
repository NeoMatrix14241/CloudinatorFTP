#!/usr/bin/env python3
"""
Development Server for CloudinatorFTP
This file runs the Flask development server for testing and debugging.
Enhanced to match ASGI configuration capabilities.
"""

import os
import sys
from datetime import timedelta

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Set environment variables for better development experience
os.environ["PYTHONUNBUFFERED"] = (
    "1"  # Immediate console output (like ASGI access_log=True)
)
os.environ["FLASK_ENV"] = "development"

# Import the Flask application
# ensure_dirs() is called inside app.py before anything else loads.
from app import app

if __name__ == "__main__":
    # Configure Flask app to match ASGI capabilities
    app.config.update(
        # Large file handling (equivalent to h11_max_incomplete_event_size=None)
        MAX_CONTENT_LENGTH=None,  # No upload size limit (like ASGI)
        # Connection/session settings (equivalent to timeout_keep_alive=0)
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),  # 24 hours — matches app.py
        SEND_FILE_MAX_AGE_DEFAULT=0,  # No caching for development
        # Development optimizations
        TESTING=False,
        DEBUG=True,
        THREADED=True,  # Multi-threading (equivalent to limit_concurrency=50)
        # Error handling (equivalent to graceful error handling in ASGI)
        PROPAGATE_EXCEPTIONS=True,
        PRESERVE_CONTEXT_ON_EXCEPTION=None,
        # Template and static file settings for development
        TEMPLATES_AUTO_RELOAD=True,
        EXPLAIN_TEMPLATE_LOADING=False,
    )

    print("🧪 Starting CloudinatorFTP Development Server...")
    print("⚠️  WARNING: This is for DEVELOPMENT/TESTING only!")
    print("🌐 Server running on http://localhost:5000")
    print("🔧 Configuration matching ASGI setup:")
    print("   • Debug mode: ON - Auto-reload enabled")
    print("   • Threading: Enabled (concurrent requests supported)")
    print("   • Upload size limit: NONE (unlimited like ASGI)")
    print("   • Request timeout: System default (no artificial limits)")
    print("   • Max requests: No limit (no auto-restart like ASGI)")
    print("   • Buffer size: Unlimited (like ASGI h11_max_incomplete_event_size=None)")
    print("   • Access logging: Enabled in debug mode")
    print("📁 Press Ctrl+C to stop the server")
    print()

    # Additional development info
    from config import ROOT_DIR

    print(f"📋 Using storage directory: {ROOT_DIR}")

    if os.name == "nt":
        print(f"📁 Windows location: {ROOT_DIR}")
    else:
        print(f"📁 Unix location: {ROOT_DIR}")
    print()

    try:
        from waitress import serve

        print("🚀 Starting Waitress server...")
        print("✅ HTTP keep-alive enabled — TCP connections reused (fixes 16k crash)")
        print("✅ SSE streaming enabled — real-time updates work")
        serve(
            app,
            host="0.0.0.0",
            port=5000,
            threads=24,  # Increased: resume can briefly spike to N_groups concurrent uploads
            connection_limit=500,
            channel_timeout=30,  # Reduced from 120s: frees threads faster after hard refresh/disconnect
            # 30s is safe because upload chunks complete in seconds.
            # SSE clients auto-reconnect when the channel closes.
            cleanup_interval=5,  # More frequent cleanup of dead channels (was 10)
            asyncore_use_poll=True,
        )
    except ImportError:
        print("⚠️  Waitress not installed — run: pip install waitress")
        print("⚠️  Falling back to Flask dev server (16k file upload limit applies)")
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=True,
            threaded=True,
            use_reloader=True,
            use_debugger=True,
        )
    except KeyboardInterrupt:
        print("\n👋 Development server stopped by user")
    except Exception as e:
        print(f"💥 Server error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
