@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto no_python

python server.py %*
if errorlevel 1 pause
exit /b 0

:no_python
echo.
echo   Python was not found.
echo   Please install Python 3.9 or newer:
echo       https://www.python.org/downloads/
echo   During setup, check "Add Python to PATH".
echo.
pause
exit /b 1
