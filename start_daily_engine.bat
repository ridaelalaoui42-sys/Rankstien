@echo off
echo Starting RankStein Daily Engine (Infinite Loop)...
set PYTHONHOME=
set UV_INTERNAL__PYTHONHOME=
set PYTHONPATH=.
python backend\scripts\daily_engine.py
pause
