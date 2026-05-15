@echo off
cd /d "%~dp0"
echo [RankStein] Starting Pinterest Automation Supervisor...
"venv\Scripts\python.exe" run_autonomous.py run
pause
