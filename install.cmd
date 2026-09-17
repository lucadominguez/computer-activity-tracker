@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install.ps1"
if errorlevel 1 (
  echo Installation failed. Read the error above; your activity history was not reset.
  pause
  exit /b 1
)
echo Installation complete. Use the desktop shortcut or launch.cmd.
pause
