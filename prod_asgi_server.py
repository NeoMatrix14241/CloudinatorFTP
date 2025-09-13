#!/usr/bin/env python3
"""
ASGI Entry Point for CloudinatorFTP
Improved version with better error handling and timeout management.
"""

import os
import sys
import signal
import asyncio

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import Flask app
from app import app

# Create ASGI wrapper with proper configuration
try:
    from a2wsgi import WSGIMiddleware
    # a2wsgi.WSGIMiddleware only takes the WSGI app as parameter
    application = WSGIMiddleware(app)
    print("🔧 Using a2wsgi wrapper for Flask-to-ASGI conversion")
except ImportError:
    print("❌ a2wsgi not found - please install: pip install a2wsgi")
    print("🔄 Falling back to direct WSGI mode")
    application = app

# Graceful shutdown handler
def signal_handler(signum, frame):
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    # Import configuration
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
    
    # Start server with improved configuration
    try:
        print("🚀 Starting CloudinatorFTP with Uvicorn ASGI Server...")
        print("⚠️  For PRODUCTION use only!")
        print("🌐 Server running on http://localhost:5000")
        print("📁 Press Ctrl+C to stop the server")
        print()
        
        import uvicorn
        
        # Optimized Uvicorn configuration for concurrent large uploads
        config = uvicorn.Config(
            app=application,  # Use the ASGI-wrapped application
            host="0.0.0.0",
            port=5000,
            workers=4,  # Single worker for development/small deployments
            
            # NO TIMEOUTS for large file operations
            timeout_keep_alive=0,        # Disable keep-alive timeout
            timeout_graceful_shutdown=60, # Only shutdown timeout
            
            # CONCURRENT UPLOAD OPTIMIZATIONS
            limit_concurrency=None,        # Allow 15 concurrent connections (10 uploads + 5 overhead)
            limit_max_requests=None,     # NO REQUEST LIMIT - essential for concurrent uploads!
            
            # Critical: Large request handling for multiple uploads
            h11_max_incomplete_event_size=None,  # No buffer size limit
            
            # Enable access logs for debugging concurrent uploads
            access_log=True,
            log_level="info",
            
            # Use ASGI interface for better concurrent handling
            interface="auto",
            
            # Production stability
            reload=False,
            lifespan="auto"
        )
        
        server = uvicorn.Server(config)
        
        # Run server with better error handling
        try:
            server.run()
        except KeyboardInterrupt:
            print("\n👋 Server stopped by user")
        except Exception as e:
            print(f"💥 Server error: {e}")
            print("🔄 Attempting graceful shutdown...")
        
    except ImportError:
        print("❌ Uvicorn not found. Installing...")
        try:
            import subprocess
            subprocess.run([
                sys.executable, "-m", "pip", "install", 
                "uvicorn[standard]", "a2wsgi"
            ], check=True)
            print("✅ Dependencies installed. Please run the script again.")
        except subprocess.CalledProcessError:
            print("❌ Failed to install dependencies. Please install manually:")
            print("   pip install uvicorn[standard] a2wsgi")
            
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        print("🔍 Check your Flask app and dependencies")
        sys.exit(1)