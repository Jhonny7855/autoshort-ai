@echo off
setlocal enabledelayedexpansion
title AUTOSHORT AI - Install

cd /d "%~dp0"

echo.
echo ===============================================
echo   AUTOSHORT AI  -  first-time setup
echo ===============================================
echo.

REM ---------- Python ----------
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [X] Python not found. Install Python 3.12 from https://python.org
    echo     and tick "Add python.exe to PATH".
    goto :fail
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

echo [1/6] Python interpreter
%PY% -V
if errorlevel 1 goto :fail

REM ---------- venv ----------
echo.
echo [2/6] Python environment
if exist ".venv\Scripts\python.exe" (
  echo     .venv already exists
) else (
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
  echo     created .venv
)

echo     installing dependencies
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

REM ---------- config ----------
echo.
echo [3/6] Configuration
if exist ".env" (
  echo     .env already exists - left untouched
) else (
  copy /y ".env.example" ".env" >nul
  echo     created .env from .env.example
)

REM ---------- ffmpeg ----------
echo.
echo [4/6] FFmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo     [!] ffmpeg is NOT on PATH. Video rendering will fail.
  echo         Install it with:  winget install Gyan.FFmpeg
  echo         Then reopen this window and run install.bat again.
) else (
  for /f "delims=" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /b "ffmpeg version"') do echo     %%v
)

REM ---------- node / web ----------
echo.
echo [5/6] Web interface
where npm >nul 2>nul
if errorlevel 1 (
  echo     [X] Node.js / npm not found. Install Node 20+ from https://nodejs.org
  goto :fail
)
pushd web
if exist "node_modules" (
  echo     node_modules already present
) else (
  call npm install
  if errorlevel 1 (
    popd
    goto :fail
  )
)
echo     building production bundle
call npm run build
if errorlevel 1 (
  popd
  goto :fail
)
popd

REM ---------- ollama ----------
echo.
echo [6/6] Local AI (Ollama)
where ollama >nul 2>nul
if errorlevel 1 (
  echo     [!] Ollama not found. Install from https://ollama.com then run:
  echo         ollama pull qwen2.5:1.5b
  echo     The app still works without it, using the template writer.
) else (
  ollama list 2>nul | findstr /i "qwen2.5 llama3.2 mistral" >nul
  if errorlevel 1 (
    echo     [!] No model installed yet. Run this to get one:
    echo         ollama pull qwen2.5:1.5b
  ) else (
    echo     models present:
    ollama list
  )
)

echo.
echo ===============================================
echo   Setup finished.
echo   Start the app with:  start.bat
echo ===============================================
echo.
pause
exit /b 0

:fail
echo.
echo [X] Setup failed. Read the message above, fix it, and run install.bat again.
echo.
pause
exit /b 1
