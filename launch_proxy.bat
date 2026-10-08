@echo off
REM Windows launcher for Odysseus Proxy (ody_proxy.py)
REM Unsets problematic env vars before starting to avoid SRE module mismatch
set PYTHONHOME=
set UV_INTERNAL__PYTHONHOME=
cd /d C:\Users\REDX420\Desktop\Rankstein
start "Odysseus Proxy" C:\Users\REDX420\Desktop\Rankstein\.venv\Scripts\python.exe C:\Users\REDX420\Desktop\Rankstein\ody_proxy.py
