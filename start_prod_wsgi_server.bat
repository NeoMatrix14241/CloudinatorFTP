@echo off
echo Starting CloudinatorFTP Production Server...
echo (Tries Gunicorn first for better SSE, falls back to Waitress)
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

REM Start the production server (tries Gunicorn first, falls back to Waitress)
echo.
echo Starting server on http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

python prod_server.py

pause
