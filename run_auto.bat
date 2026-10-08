@echo off
:: ═══════════════════════════════════════════════════════════════
:: RankStein Auto-Runner — Continuous autonomous loop.
:: Runs content cycles with configurable delay between them.
:: Usage:
::   run_auto.bat              (default: 4hr delay between cycles)
::   run_auto.bat 7200         (custom delay in seconds, e.g., 2hrs)
::   run_auto.bat 0 1          (run once with no delay, then exit)
:: ═══════════════════════════════════════════════════════════════
echo [RankStein Auto] Starting continuous autonomous mode...
echo.

set PYTHONHOME=
set UV_INTERNAL__PYTHONHOME=

set DELAY=%1
if "%DELAY%"=="" set DELAY=14400

set RUN_ONCE=%2
if "%RUN_ONCE%"=="" set RUN_ONCE=0

:loop
echo.
echo ══════════════════════════════════════════════════════════
echo [%DATE% %TIME%] Starting new cycle...
echo ══════════════════════════════════════════════════════════

python "%~dp0rankstein.py" run --all

if %ERRORLEVEL% EQU 0 (
    echo [RankStein Auto] Cycle SUCCESS.
) else (
    echo [RankStein Auto] Cycle FAILED (exit code: %ERRORLEVEL%).
)

if "%RUN_ONCE%"=="1" (
    echo [RankStein Auto] Single-run mode. Exiting.
    exit /b 0
)

echo [RankStein Auto] Sleeping %DELAY% seconds until next cycle...
timeout /t %DELAY% /nobreak >nul
goto :loop
