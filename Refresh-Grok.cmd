@echo off
setlocal

cd /d "%~dp0"
set PYTHONUTF8=1
if not defined AIRS_GROK_MODEL set AIRS_GROK_MODEL=grok-4.5
if not defined AIRS_GROK_REASONING_EFFORT set AIRS_GROK_REASONING_EFFORT=high
python "%~dp0refresh.py" --agent grok %*
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
