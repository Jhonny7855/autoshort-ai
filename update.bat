@echo off
setlocal enabledelayedexpansion
title AUTOSHORT AI - update

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv not found. Run install.bat first.
  pause
  exit /b 1
)

echo.
echo [1/3] Stopping a running server on port 8787
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8787 .*LISTENING"') do (
  taskkill /PID %%p /F >nul 2>nul
  echo     stopped PID %%p
)

echo.
echo [2/3] Updating Python dependencies
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [3/3] Rebuilding the web interface
pushd web
call npm install
if errorlevel 1 (
  popd
  goto :fail
)
call npm run build
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo.
echo ===============================================
echo   Update complete. Start with: start.bat
echo ===============================================
echo.
pause
exit /b 0

:fail
echo.
echo [X] Update failed. Read the message above.
echo.
pause
exit /b 1
