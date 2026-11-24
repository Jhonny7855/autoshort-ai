@echo off
setlocal
title AUTOSHORT AI - running

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv not found. Run install.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  if exist ".env.example" copy /y ".env.example" ".env" >nul
)
if not exist "web\dist\index.html" (
  echo [!] web\dist is missing - run install.bat to build the interface.
)

REM Refuse to start twice on the same port.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8787 .*LISTENING"') do (
  echo [!] Port 8787 is already in use by PID %%p.
  echo     Run stop.bat first if this is a stale server.
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0server"

echo.
echo Starting AUTOSHORT AI on http://127.0.0.1:8787
echo Close this window or press Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:8787"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir server

echo.
echo Server stopped.
pause
