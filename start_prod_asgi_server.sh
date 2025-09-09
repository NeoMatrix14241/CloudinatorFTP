#!/bin/bash
echo "Starting CloudinatorFTP Production ASGI Server..."
echo "(Using Uvicorn with ASGI for async capabilities)"
echo

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "No virtual environment found. Using system Python..."
fi

# Install/update dependencies including ASGI requirements
echo "Installing dependencies..."
pip install -r requirements.txt
pip install "uvicorn[standard]" asgiref

# Start the production ASGI server
echo
echo "Starting ASGI server on http://localhost:5000"
echo "Press Ctrl+C to stop the server"
echo
echo "Features:"
echo "- Async/await support via ASGI"
echo "- High-performance HTTP with httptools"
echo "- WebSocket support ready"
echo "- Better concurrency handling"
echo "- SSE (Server-Sent Events) optimized"
echo

python prod_asgi_server.py
