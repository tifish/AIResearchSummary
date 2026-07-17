@echo off
setlocal

cd /d "%~dp0"
set PYTHONUTF8=1
if not defined AIRS_CODEX_MODEL set AIRS_CODEX_MODEL=gpt-5.6-sol
if not defined AIRS_CODEX_REASONING_EFFORT set AIRS_CODEX_REASONING_EFFORT=high
python "%~dp0refresh.py" --agent codex %*
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
