@echo off
REM PromptChain launcher for Windows. Double-click this file to start the app.
cd /d "%~dp0"

set "PYCMD="
py --version >nul 2>nul
if %errorlevel%==0 set "PYCMD=py"

if not defined PYCMD (
    python --version >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10+ is required but was not found.
        echo Install it from https://www.python.org/downloads/ then run this again.
        echo During install, tick "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
    set "PYCMD=python"
)

%PYCMD% run.py
echo.
pause
