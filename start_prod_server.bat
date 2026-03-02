@echo off
echo 🧪 Starting CloudinatorFTP Production Server...
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

REM Start the production server
echo.
echo 🌐 Starting Flask production server on http://localhost:5000
echo 🔧 Debug mode: OFF - Auto-reload disabled
echo 📁 Press Ctrl+C to stop the server
echo.

python dev_server.py

pause
