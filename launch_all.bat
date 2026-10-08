@echo off
echo WARNING: launch_all.bat is deprecated. Please use start_all_services.ps1 or 'python rankstein.py suite start'.
echo Delegating to rankstein.py suite start...
cd /d %~dp0
.venv\Scripts\python.exe rankstein.py suite start
pause
