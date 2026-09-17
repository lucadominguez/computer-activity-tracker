param([switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    $BasePython = $null
    foreach ($Name in @('py.exe', 'python.exe', 'python3.exe')) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if (-not $Command -or $Command.Source -like '*\WindowsApps\*') { continue }
        $Arguments = @('-c', 'import sys; assert sys.version_info >= (3, 10); print(sys.executable)')
        if ($Name -eq 'py.exe') { $Arguments = @('-3') + $Arguments }
        $Candidate = & $Command.Source @Arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $Candidate -and (Test-Path ($Candidate | Select-Object -Last 1))) {
            $BasePython = $Candidate | Select-Object -Last 1
            break
        }
    }
    if (-not $BasePython) { throw 'Install Python 3.10 or newer from python.org with the Python launcher enabled, then run install.cmd again.' }
    & $BasePython -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the isolated Python environment.' }
}
& $VenvPython -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
if ($LASTEXITCODE -ne 0) { throw 'The existing virtual environment needs Python 3.10 or newer.' }
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-windows.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the Windows recording dependency.' }
& $VenvPython (Join-Path $PSScriptRoot 'windows_activity_tracker.py') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Isolated storage self-test failed.' }
& $VenvPython (Join-Path $Root 'activity_tracker.py') --help
if ($LASTEXITCODE -ne 0) { throw 'The dashboard launcher could not load.' }
if (-not $NoShortcut) { & (Join-Path $PSScriptRoot 'create_shortcut.ps1') }
Write-Output 'INSTALL PASS. Open the desktop shortcut or launch.cmd to start the visible dashboard.'
Write-Output 'Installation does not start recording, enable autostart, reset history, or stop any existing collector.'
