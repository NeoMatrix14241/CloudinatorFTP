#!/usr/bin/env python3
"""
ASGI Entry Point for CloudinatorFTP
This file serves as the ASGI application entry point for production deployment using Uvicorn.
"""

import os
import sys

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import Flask app and create ASGI wrapper
from app import app

# Use a2wsgi for superior Flask compatibility
try:
    from a2wsgi import WSGIMiddleware
    application = WSGIMiddleware(app)
    print("🔧 Using a2wsgi wrapper for optimal Flask compatibility")
except ImportError:
    print("❌ a2wsgi not found - please install: pip install a2wsgi")
    print("🔄 Falling back to direct WSGI mode")
    application = app  # Direct WSGI fallback

if __name__ == "__main__":
    # Import the configuration (will auto-initialize storage and server config)
    from config import load_server_config, ROOT_DIR
    
    # Load server configuration
    load_server_config()
    
    print(f"📋 Using storage directory: {ROOT_DIR}")
    
    # Platform-specific storage info
    if os.name == 'nt':
        print(f"📁 Windows location: {ROOT_DIR}")
        print("💡 Access via File Explorer or any file manager")
    else:
        print(f"📁 Unix location: {ROOT_DIR}")
        print("💡 Access via your file manager")
    
    # Try Uvicorn ASGI server with better Flask compatibility
    try:
        print("🚀 Starting CloudinatorFTP with Uvicorn ASGI Server...")
        print("⚠️  For PRODUCTION use only!")
        print("🌐 Server running on http://localhost:5000")
        print("📁 Press Ctrl+C to stop the server")
        print()
        
        # Try direct uvicorn import first with Flask-optimized settings
        try:
            import uvicorn
            
            # Check if we have a proper ASGI app or need WSGI mode
            if hasattr(application, '__call__') and not hasattr(application, 'lifespan'):
                print("🔧 Detected WSGI app, using WSGI mode in Uvicorn")
                # Use WSGI interface in Uvicorn for better Flask compatibility
                uvicorn.run(
                    app,  # Use Flask app directly
                    host="0.0.0.0",
                    port=5000,
                    workers=1,
                    access_log=True,
                    timeout_keep_alive=60,
                    log_level="info",
                    interface="wsgi"  # Force WSGI interface
                )
            else:
                print("🔧 Using ASGI mode")
                uvicorn.run(
                    "prod_asgi_server:application",
                    host="0.0.0.0",
                    port=5000,
                    workers=1,
                    access_log=True,
                    timeout_keep_alive=60,
                    log_level="info",
                    reload=False,  # Disable reload for stability
                )
        except ImportError:
            # Fallback to subprocess method
            import subprocess
            cmd = [
                sys.executable, "-m", "uvicorn",
                "prod_asgi_server:application",
                "--host", "0.0.0.0",
                "--port", "5000",
                "--workers", "1",
                "--access-log",
                "--timeout-keep-alive", "60",
                "--log-level", "info",
                "--interface", "auto",  # Let uvicorn detect best interface
            ]
            subprocess.run(cmd, check=True)
        
    except (ImportError, FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"⚠️  Uvicorn error: {e}")
        print("⚠️  Trying to install uvicorn...")
        try:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "uvicorn[standard]"], check=True)
            print("✅ Uvicorn installed. Please run the script again.")
        except subprocess.CalledProcessError:
            print("❌ Failed to install uvicorn. Please install manually:")
            print("   pip install uvicorn[standard]")
            
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
