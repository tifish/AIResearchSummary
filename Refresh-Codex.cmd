@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Refresh.ps1" -Agent codex
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
