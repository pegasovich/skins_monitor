# CS2 Collectibles Monitor Quick Launcher for PowerShell
$Host.UI.RawUI.WindowTitle = "CS2 Collectibles Monitor"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       STARTING CS2 COLLECTIBLES MONITOR DAEMON" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

$env:PYTHONPATH = "src"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "[.venv not found] Creating virtual environment and installing dependencies..." -ForegroundColor Yellow
    python -m venv .venv
    & ".\.venv\Scripts\python.exe" -m pip install -e .
    Write-Host "Setup complete!" -ForegroundColor Green
}

& ".\.venv\Scripts\python.exe" -m collectibles.main
