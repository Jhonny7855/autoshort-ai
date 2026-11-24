@echo off
setlocal enabledelayedexpansion
title AUTOSHORT AI - stop

echo Looking for AUTOSHORT AI on port 8787...
set "FOUND=0"

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8787 .*LISTENING"') do (
  echo Stopping PID %%p
  taskkill /PID %%p /F >nul 2>nul
  set "FOUND=1"
)

if "!FOUND!"=="0" (
  echo Nothing was listening on port 8787.
) else (
  echo Stopped.
)

echo.
pause
