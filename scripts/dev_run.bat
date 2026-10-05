@echo off
rem Windows command prompt wrapper for dev_run.ps1. Forwards all args and the exit code.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev_run.ps1" %*
exit /b %ERRORLEVEL%
