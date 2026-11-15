@echo off
title ARES - Astronaut Health Command
cd /d "%~dp0"
echo.
echo   ARES - Autonomous Risk Evaluation ^& Emergency Support
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo   Python was not found. Install Python 3.11+ from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist ".ares_installed" (
  echo   First start: installing required packages, this takes a few minutes...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo   Package installation failed. See the message above.
    pause
    exit /b 1
  )
  echo done> .ares_installed
)
python run_ares.py
echo.
echo   ARES stopped.
pause
