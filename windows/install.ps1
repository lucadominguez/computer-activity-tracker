$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Join-Path $env:USERPROFILE 'computer-activity-tracker'
$WindowsDir = Join-Path $Root 'windows'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA 'HermesPTT\venv\Scripts\python.exe'),
        (Join-Path $env:APPDATA 'uv\python\cpython-3.11-windows-x86_64-none\python.exe'),
        (Join-Path $env:USERPROFILE 'reading-interest-collector\.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python3.13.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python.exe')
    )
    $BasePython = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $BasePython) {
        throw 'No usable Windows Python runtime found.'
    }
    & $BasePython -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the tracker virtual environment.' }
}

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $WindowsDir 'requirements-windows.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Windows tracker dependencies.' }

$SelfTest = Join-Path $Root 'selftest-data'
& $VenvPython (Join-Path $WindowsDir 'windows_activity_tracker.py') --self-test --data-dir $SelfTest
if ($LASTEXITCODE -ne 0) { throw 'Windows tracker self-test failed.' }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $WindowsDir 'create_shortcut.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Desktop shortcut creation failed.' }

Write-Output "INSTALL PASS root=$Root python=$VenvPython"
