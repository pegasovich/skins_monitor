# CS2 Collectibles Monitor Quick Launcher for PowerShell
$Host.UI.RawUI.WindowTitle = "CS2 Collectibles Monitor"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       STARTING CS2 COLLECTIBLES MONITOR DAEMON" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

$env:PYTHONPATH = "src"

if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" -m collectibles.main
} else {
    python -m collectibles.main
}
