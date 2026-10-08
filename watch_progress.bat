@echo off
title RankStein Upload Monitor
set PYTHONHOME=
set UV_INTERNAL__PYTHONHOME=
:loop
cls
echo ==================================================
echo         RANKSTEIN BATCH UPLOAD MONITOR
echo ==================================================
python run_autonomous.py status
echo.
echo --- Latest Automation Engine Logs ---
powershell -Command "Get-Content data\logs\automation.log -Tail 15"
echo.
echo ==================================================
echo Updating again in 20 seconds... Press Ctrl+C to stop.
timeout /t 20 /nobreak >nul
goto loop
