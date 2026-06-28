@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Refresh.ps1" -Agent claude
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
