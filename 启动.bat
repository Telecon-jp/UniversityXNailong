@echo off
cd /d "%~dp0"

set "PY=E:\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" app.py

echo.
echo [server stopped] press any key to close...
pause >nul
