@echo off
echo Starting CloudinatorFTP with Waitress WSGI Server...
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

REM Start the WSGI server
echo.
echo Starting server on http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

waitress-serve --host=0.0.0.0 --port=5000 --threads=8 --channel-timeout=120 --max-request-body-size=1099511627776 wsgi:application

pause
