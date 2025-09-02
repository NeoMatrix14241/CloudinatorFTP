@echo off
echo 🧪 Starting CloudinatorFTP Development Server...
echo ⚠️  WARNING: This is for DEVELOPMENT/TESTING only!
echo.

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found. Using system Python...
)

REM Install/update dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Start the development server
echo.
echo 🌐 Starting Flask development server on http://localhost:5000
echo 🔧 Debug mode: ON - Auto-reload enabled
echo 📁 Press Ctrl+C to stop the server
echo.

python dev_server.py

pause
