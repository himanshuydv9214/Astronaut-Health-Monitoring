# ARES - put an "ARES" shortcut on the Desktop that opens the desktop window straight from this folder,
# WITHOUT building an .exe (uses the project's .venv). Run once:
#     powershell -ExecutionPolicy Bypass -File desktop\create_shortcut.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\python.exe"
$pyw  = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Host "No .venv found - run START_ARES.bat once first (it creates it)."; exit 1 }
& $py -c "import webview" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Installing pywebview into .venv ..."; & $py -m pip install "pywebview>=5.3" }
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "ARES.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$root\desktop\ares_desktop.py`""
$s.WorkingDirectory = $root
$s.IconLocation = "$root\desktop\assets\ares.ico"
$s.Description = "ARES Astronaut Health Command"
$s.Save()
Write-Host "Created $lnk - double-click it to start ARES (no terminal window)."
