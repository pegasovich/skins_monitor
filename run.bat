@echo off
title CS2 Collectibles Monitor
cd /d "%~dp0"

echo ========================================================
echo        STARTING CS2 COLLECTIBLES MONITOR DAEMON
echo ========================================================
echo.

set PYTHONPATH=src
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m collectibles.main
) else (
    python -m collectibles.main
)

pause
