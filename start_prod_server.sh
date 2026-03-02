#!/bin/bash
echo "🧪 Starting CloudinatorFTP Production Server..."
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

# Start the production server
echo
echo "🌐 Starting Flask production server on http://localhost:5000"
echo "🔧 Debug mode: OFF - Auto-reload disabled"
echo "📁 Press Ctrl+C to stop the server"
echo

python prod_server.py
