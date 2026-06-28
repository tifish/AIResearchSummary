@echo off
setlocal

cd /d "%~dp0"
set PYTHONUTF8=1
python "%~dp0refresh.py" --agent codex
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
