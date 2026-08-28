@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0backend"

set PYTHONPATH=%~dp0;%PYTHONPATH%

echo.
echo ==============================================
echo   Data AI Agent - one-click launcher (Windows)
echo ==============================================
echo.

if exist venv\Scripts\python.exe goto :venv_ok
echo [1/4] Creating Python virtual environment...
py -3 -m venv venv 2>nul
if errorlevel 1 python -m venv venv
if errorlevel 1 (
    echo.
    echo ERROR: Could not create the virtual environment.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and make sure to tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)
:venv_ok

call venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR: Could not install dependencies. Check your internet connection.
    pause
    exit /b 1
)

if exist .env goto :env_ok
copy .env.example .env >nul
echo.
echo =============================================================
echo   FIRST-TIME SETUP - one step needed:
echo   A file opened in Notepad (backend\.env).
echo   Paste your OpenRouter API key after OPENROUTER_API_KEY= and save.
echo   Get a FREE key at:  https://openrouter.ai/keys
echo   Then run this script again.
echo =============================================================
echo.
start notepad .env
pause
exit /b 0
:env_ok

echo [3/4] Starting server...
start "" http://localhost:8000
echo [4/4] Server running at http://localhost:8000  (press Ctrl+C to stop)
echo.
python -m uvicorn app:app --port 8000
