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
    # Use Waitress for production deployment
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
            threads=8,
            channel_timeout=120,
            cleanup_interval=30,
            max_request_body_size=1099511627776  # 1TB limit (effectively unlimited)
        )
    except ImportError:
        print("⚠️  Waitress not installed. Installing...")
        os.system("pip install waitress")
        print("✅ Please run the script again.")
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
