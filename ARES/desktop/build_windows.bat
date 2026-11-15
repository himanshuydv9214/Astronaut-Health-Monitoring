@echo off
rem ============================================================================================
rem  ARES - build the Windows desktop app, the portable zip and the installer.
rem  Run on Windows 10/11 x64 from the ARES folder (double-click works too). Needs internet ONCE,
rem  to install the build tools; the results run fully offline and need no Python or Node.js.
rem    dist\ARES\ARES.exe                         the app (one folder)
rem    dist\ARES-0.5.0-portable-win64.zip         portable: unzip anywhere, run ARES.exe, data stays next to it
rem    dist\installer\ARES-Setup-0.5.0.exe        installer (if Inno Setup 6 is installed)
rem ============================================================================================
setlocal
cd /d "%~dp0\.."
set ROOT=%CD%
set VERSION=0.5.0

if not exist ".venv\Scripts\python.exe" (
  echo [1/6] Creating Python environment .venv ...
  py -3 -m venv .venv || python -m venv .venv || goto :nopython
  ".venv\Scripts\python" -m pip install --upgrade pip
  ".venv\Scripts\python" -m pip install -r requirements.txt || goto :fail
) else (
  echo [1/6] Using existing .venv
)
echo [2/6] Installing build tools (PyInstaller, pywebview) ...
".venv\Scripts\python" -m pip install -r desktop\requirements-desktop.txt || goto :fail

if not exist "ares\web3d_dist\index.html" (
  echo [!] The interface is not built: ares\web3d_dist\index.html is missing.
  echo     Build it once with Node.js:  cd web3d ^&^& npm ci ^&^& npm run build
  goto :fail
)
if not exist "models\anomaly_iforest.joblib" (
  echo [!] Trained models missing in models\  -  run: .venv\Scripts\python scripts\train_models.py
  goto :fail
)
if not exist "desktop\assets\ares.ico" ".venv\Scripts\python" desktop\make_icon.py

echo [3/6] Building dist\ARES\ARES.exe (takes a few minutes) ...
if exist build\ares rmdir /s /q build\ares
if exist dist\ARES rmdir /s /q dist\ARES
".venv\Scripts\python" -m PyInstaller --noconfirm --clean --distpath dist --workpath build\ares desktop\ares.spec || goto :fail

echo [4/6] Self-test of the built app (starts it hidden, checks every component, shuts it down) ...
set ARES_DATA_DIR=%ROOT%\build\selftest-data
if exist "%ARES_DATA_DIR%" rmdir /s /q "%ARES_DATA_DIR%"
"dist\ARES\ARES.exe" --self-test > build\selftest.json
if errorlevel 1 (
  type build\selftest.json
  echo [!] Self-test FAILED - see build\selftest.json and %ARES_DATA_DIR%\logs
  goto :fail
)
set ARES_DATA_DIR=
echo     self-test passed  (build\selftest.json)

echo [5/6] Portable zip ...
if exist dist\ARES-portable rmdir /s /q dist\ARES-portable
xcopy /e /i /q dist\ARES dist\ARES-portable\ARES >nul
echo ARES portable build: data is stored in the "data" folder next to ARES.exe> dist\ARES-portable\ARES\portable.flag
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\ARES-portable\ARES' -DestinationPath 'dist\ARES-%VERSION%-portable-win64.zip'" || goto :fail
rmdir /s /q dist\ARES-portable

echo [6/6] Installer ...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
  echo     Inno Setup 6 not found - skipping the installer. Install it from https://jrsoftware.org/isdl.php
  echo     ^(or: winget install JRSoftware.InnoSetup^) and run this script again.
) else (
  "%ISCC%" /Qp desktop\installer.iss || goto :fail
  echo     dist\installer\ARES-Setup-%VERSION%.exe
)

echo.
echo DONE.  App: dist\ARES\ARES.exe   Portable: dist\ARES-%VERSION%-portable-win64.zip
echo Optional: offline reliability tests (turn Wi-Fi off first):
echo     .venv\Scripts\python desktop\offline_tests.py --app dist\ARES\ARES.exe
pause
exit /b 0

:nopython
echo [!] Python 3.11+ is needed to BUILD ARES (not to run it). Install it from https://www.python.org/downloads/
:fail
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
