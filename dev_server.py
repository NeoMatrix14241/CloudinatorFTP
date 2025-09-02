#!/usr/bin/env python3
"""
Development Server for CloudinatorFTP
This file runs the Flask development server for testing and debugging.
"""

import os
import sys

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the Flask application
from app import app

if __name__ == "__main__":
    print("🧪 Starting CloudinatorFTP Development Server...")
    print("⚠️  WARNING: This is for DEVELOPMENT/TESTING only!")
    print("🌐 Server running on http://localhost:5000")
    print("🔧 Debug mode: ON - Auto-reload enabled")
    print("📁 Press Ctrl+C to stop the server")
    print()
    
    # Run Flask development server with debug mode
    app.run(
        host='0.0.0.0', 
        port=5000, 
        debug=True,           # Enable debug mode
        threaded=True,        # Enable threading
        use_reloader=True,    # Auto-reload on code changes
        use_debugger=True     # Enable interactive debugger
    )
