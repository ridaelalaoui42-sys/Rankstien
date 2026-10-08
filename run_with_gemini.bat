@echo off
setlocal
set PYTHONHOME=
set UV_INTERNAL__PYTHONHOME=
echo ==============================================================
echo RankStein AI Engine - Single Cycle Execution
echo ==============================================================
echo.

set PROMPT_FILE=%~dp0gemini_rankstein_prompt.md
set COMMAND_PROMPT=Execute the workflow for the next pending keyword.

echo [Preflight] Validating Gemini CLI and MCP runtime...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev\start_agentmemory.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] AgentMemory failed to start. Fix the issue above before starting an autonomous cycle.
    exit /b %ERRORLEVEL%
)
python "%~dp0scripts\dev\validate_gemini_runtime.py"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Runtime preflight failed. Fix the issue above before starting an autonomous cycle.
    exit /b %ERRORLEVEL%
)
echo.

echo [Model 1/2] Trying gemini-2.5-flash (primary - confirmed working)...
call gemini -p "%COMMAND_PROMPT%" --model gemini-2.5-flash --yolo < "%PROMPT_FILE%"
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Cycle completed with gemini-2.5-flash.
    exit /b 0
)
echo [FAIL] gemini-2.5-flash failed with exit code %ERRORLEVEL%.

echo.
echo [Model 2/2] Trying gemini-2.5-pro (fallback - watch quota)...
call gemini -p "%COMMAND_PROMPT%" --model gemini-2.5-pro --yolo < "%PROMPT_FILE%"
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Cycle completed with gemini-2.5-pro.
    exit /b 0
)
echo [FAIL] gemini-2.5-pro failed with exit code %ERRORLEVEL%.

echo.
echo [ERROR] All Gemini models failed to execute the cycle.
echo [NOTE] All gemini-3.x model IDs return 404 on this account/CLI as of 2026-05-03.
echo [NOTE] gemini-2.5-pro hits QUOTA_EXHAUSTED quickly; gemini-2.5-flash is the daily driver.
exit /b 1
