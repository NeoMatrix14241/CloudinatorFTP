#!/bin/bash
echo "Starting CloudinatorFTP with Gunicorn WSGI Server..."
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

# Start the WSGI server
echo
echo "Starting server on http://localhost:5000"
echo "Press Ctrl+C to stop the server"
echo

gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 --access-logfile - --error-logfile - wsgi:application
