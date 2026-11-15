@echo off
title CS2 Collectibles Monitor
cd /d "%~dp0"

echo ========================================================
echo        STARTING CS2 COLLECTIBLES MONITOR DAEMON
echo ========================================================
echo.

set PYTHONPATH=src
if not exist .venv\Scripts\python.exe (
    echo [.venv not found] Creating virtual environment and installing dependencies...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -e .
    echo Setup complete!
    echo.
)

.venv\Scripts\python.exe -m collectibles.main

pause
