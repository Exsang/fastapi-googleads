@echo off
REM === Activate venv and start FastAPI + ngrok ===
cd %USERPROFILE%\Desktop\fastapi-googleads
call venv\Scripts\activate

start "" uvicorn main:APP --reload --host 0.0.0.0 --port 8000
timeout /t 3 /nobreak >nul
start "" ngrok http 8000

echo.
echo ✅ FastAPI and ngrok are running!
echo Open http://127.0.0.1:8000/docs (local)
echo Check ngrok terminal for your public HTTPS URL.
pause
