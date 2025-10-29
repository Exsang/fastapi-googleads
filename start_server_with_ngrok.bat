@echo off
setlocal

REM === Change these paths if your project lives elsewhere ===
cd /d "%USERPROFILE%\Desktop\fastapi-googleads"

REM --- Activate virtual environment (Python 3.12) ---
if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo [ERROR] venv not found: venv\Scripts\activate.bat
  echo Create it with:  python -m venv venv
  exit /b 1
)

REM --- Load .env automatically via app.settings or app.main (dotenv) ---

REM --- START uvicorn (reload for dev) ---
start "" cmd /c uvicorn app.main:APP --reload

REM --- OPTIONAL: start ngrok for port 8000 (uncomment if desired) ---
REM start "" cmd /c ngrok http 8000

REM --- Open the docs in default browser ---
start "" http://127.0.0.1:8000/docs

endlocal
