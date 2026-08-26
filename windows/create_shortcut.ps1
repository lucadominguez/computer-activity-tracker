$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Join-Path $env:USERPROFILE 'computer-activity-tracker'
$Script = Join-Path $Root 'windows\windows_activity_tracker.py'
$Pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Desktop = [Environment]::GetFolderPath('Desktop')
$LinkPath = Join-Path $Desktop 'Computer Activity Tracker.lnk'

if (-not (Test-Path $Pythonw)) { throw "Missing pythonw.exe: $Pythonw" }
if (-not (Test-Path $Script)) { throw "Missing tracker script: $Script" }

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($LinkPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '"' + $Script + '" --forever'
$Shortcut.WorkingDirectory = Join-Path $Root 'windows'
$Shortcut.Description = 'Start the local Windows computer activity tracker'
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,21"
$Shortcut.Save()

Write-Output "SHORTCUT PASS path=$LinkPath"
