@echo off
echo Starting CloudinatorFTP Production ASGI Server...
echo (Using Uvicorn with ASGI for async capabilities)
echo.

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found. Using system Python...
)

REM Install/update dependencies including ASGI requirements
echo Installing dependencies...
pip install -r requirements.txt
pip install uvicorn[standard] asgiref

REM Start the production ASGI server
echo.
echo Starting ASGI server on http://localhost:5000
echo Press Ctrl+C to stop the server
echo.
echo Features:
echo - Async/await support via ASGI
echo - High-performance HTTP with httptools
echo - WebSocket support ready
echo - Better concurrency handling
echo - SSE (Server-Sent Events) optimized
echo.

python prod_asgi_server.py

pause
