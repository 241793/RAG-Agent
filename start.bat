@echo off
REM One-click start (unified single port 6677: API + frontend)
setlocal

echo [1/3] Init database and admin account...
cd /d "%~dp0backend"
if not exist ".venv" (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not exist ".env" copy .env.example .env >nul
.venv\Scripts\python.exe scripts\seed.py

echo [2/3] Build frontend...
cd /d "%~dp0web"
if not exist "node_modules" npm install
call npm run build

echo [3/3] Starting server on http://127.0.0.1:6677 ...
cd /d "%~dp0backend"
start "RAG-Server" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 6677"

echo.
echo Done. Open http://127.0.0.1:6677  login: admin / admin123
endlocal
