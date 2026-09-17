$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root 'activity_tracker.py'
$Pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not (Test-Path $Pythonw)) { throw 'Missing pythonw.exe. Run install.cmd first.' }
if (-not (Test-Path $Script)) { throw 'Missing application launcher.' }
$Shell = New-Object -ComObject WScript.Shell
foreach($Name in @('Passage.lnk','Computer Activity Tracker.lnk')) {
    $LinkPath = Join-Path $Desktop $Name
    if(Test-Path $LinkPath){
        $Existing=$Shell.CreateShortcut($LinkPath)
        if($Existing.Arguments -notlike '*activity_tracker.py*'){throw "Unrelated shortcut exists: $Name"}
    }
    $Shortcut = $Shell.CreateShortcut($LinkPath)
    $Shortcut.TargetPath = $Pythonw
    $Shortcut.Arguments = '"' + $Script + '"'
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.Description = 'Passage Windows adaptation: private screenshots, OCR and activity history'
    $Shortcut.IconLocation = (Join-Path $Root 'activity_app\static\passage.ico') + ',0'
    $Shortcut.Save()
    $Verified = $Shell.CreateShortcut($LinkPath)
    if ($Verified.TargetPath -ne $Pythonw -or $Verified.Arguments -ne $Shortcut.Arguments) { throw 'Shortcut verification failed.' }
    Write-Output "SHORTCUT PASS path=$LinkPath"
}
