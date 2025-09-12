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
os.environ['PYTHONUNBUFFERED'] = '1'  # Immediate console output (like ASGI access_log=True)
os.environ['FLASK_ENV'] = 'development'

# Import the Flask application
from app import app

if __name__ == "__main__":
    # Configure Flask app to match ASGI capabilities
    app.config.update(
        # Large file handling (equivalent to h11_max_incomplete_event_size=None)
        MAX_CONTENT_LENGTH=None,  # No upload size limit (like ASGI)
        
        # Connection/session settings (equivalent to timeout_keep_alive=0)
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),  # Long sessions
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
    
    if os.name == 'nt':
        print(f"📁 Windows location: {ROOT_DIR}")
    else:
        print(f"📁 Unix location: {ROOT_DIR}")
    print()
    
    try:
        # Run Flask development server (configured to match ASGI behavior)
        app.run(
            host='0.0.0.0',       # Same as ASGI
            port=5000,            # Same as ASGI  
            debug=True,           # Enable debug mode
            threaded=True,        # Enable threading (concurrent handling like ASGI)
            use_reloader=True,    # Auto-reload on code changes
            use_debugger=True,    # Enable interactive debugger
        )
    except KeyboardInterrupt:
        print("\n👋 Development server stopped by user")
    except Exception as e:
        print(f"💥 Server error: {e}")
        print("🔍 Check your Flask app and dependencies")
        sys.exit(1)