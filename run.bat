@echo off
echo === Script started ===
:: Dyno Control Software — Windows launcher
:: Double-click this file to install dependencies (first time) and launch.

cd /d "%~dp0"
echo Working directory: %cd%

echo.

:: Check Python is available
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from https://python.org
    pause
    exit /b 1
)
echo Passed Python check
pause

echo.
:: Install / upgrade requirements silently on first run
echo === Installing requirements ===
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements. Check your internet connection.
    pause
    exit /b 1
)
echo Requirements installed
pause

echo.
echo === Launching main.py ===
:: Launch
echo Launching main.py
python main.py
echo main.py exited with code %errorlevel%
pause
