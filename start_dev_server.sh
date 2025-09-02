#!/bin/bash
echo "🧪 Starting CloudinatorFTP Development Server..."
echo "⚠️  WARNING: This is for DEVELOPMENT/TESTING only!"
echo

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "No virtual environment found. Using system Python..."
fi

# Install/update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Start the development server
echo
echo "🌐 Starting Flask development server on http://localhost:5000"
echo "🔧 Debug mode: ON - Auto-reload enabled"
echo "📁 Press Ctrl+C to stop the server"
echo

python dev_server.py
