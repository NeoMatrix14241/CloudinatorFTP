#!/usr/bin/env python3
"""
WSGI Entry Point for CloudinatorFTP
This file serves as the WSGI application entry point for production deployment.
"""

import os
import sys

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the Flask application
from app import app

# WSGI application
application = app

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
    
    # Try Gunicorn first (better SSE support), fallback to Waitress
    try:
        import subprocess
        print("🚀 Starting CloudinatorFTP with Gunicorn WSGI Server...")
        print("⚠️  For PRODUCTION use only!")
        print("🌐 Server running on http://localhost:5000")
        print("📁 Press Ctrl+C to stop the server")
        print()
        
        # Gunicorn command with optimal settings for SSE
        cmd = [
            sys.executable, "-m", "gunicorn",
            "--bind", "0.0.0.0:5000",
            "--workers", "1",  # Single worker for SSE compatibility
            "--worker-class", "sync",  # Synchronous worker
            "--timeout", "300",  # 5 minute timeout for SSE connections
            "--keep-alive", "5",  # Keep connections alive
            "--max-requests", "0",  # No max requests
            "--preload",  # Preload the application
            "prod_server:application"  # Use this file as WSGI module
        ]
        
        # Start gunicorn
        subprocess.run(cmd, check=True)
        
    except (ImportError, FileNotFoundError, subprocess.CalledProcessError):
        print("⚠️  Gunicorn not available, falling back to Waitress...")
        try:
            from waitress import serve
            print("🚀 Starting CloudinatorFTP with Waitress WSGI Server...")
            print("🌐 Server running on http://localhost:5000")
            print("📁 Press Ctrl+C to stop the server")
            print()
            
            serve(
                application,
                host='0.0.0.0',
                port=5000,
                threads=8,                           # Reduced for better SSE handling
                connection_limit=1000,               # Higher connection limit for SSE
                asyncore_use_poll=True,              # Better performance on Windows
                channel_timeout=600,                 # 10 minutes for SSE connections
                cleanup_interval=30,                 # Faster cleanup interval
                recv_bytes=65536,                    # 64KB buffer
                send_bytes=65536,                    # 64KB buffer for SSE
                ident='CloudinatorFTP/1.0',          # Custom server identification
                url_scheme='http',                   # Explicit scheme for session handling
                max_request_body_size=1099511627776, # 1TB limit (effectively unlimited)
                # SSE-specific optimizations
                outbuf_overflow=1048576,             # 1MB output buffer
                outbuf_high_watermark=16384,         # 16KB high watermark
                inbuf_overflow=524288,               # 512KB input buffer
                # Disable output buffering for real-time streams
                expose_tracebacks=False              # Security
            )
        except ImportError:
            print("⚠️  Neither Gunicorn nor Waitress installed. Installing Waitress...")
            os.system("pip install waitress")
            print("✅ Please run the script again.")
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
