@echo off
cd /d "%~dp0"
echo [RankStein] Enqueueing batch of unpinned posts...
"venv\Scripts\python.exe" run_autonomous.py enqueue-batch
pause
