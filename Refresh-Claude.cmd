@echo off
setlocal

cd /d "%~dp0"
set PYTHONUTF8=1
if not defined AIRS_CLAUDE_MODEL set AIRS_CLAUDE_MODEL=claude-fable-5
if not defined AIRS_CLAUDE_EFFORT set AIRS_CLAUDE_EFFORT=high
python "%~dp0refresh.py" --agent claude %*
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
