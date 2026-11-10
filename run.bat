@echo off
setlocal

:: =============================================================================
:: Dyno Control Software — Windows GUI Launcher
:: =============================================================================
cd /d "%~dp0"

echo Starting Dyno Control Software...

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" main.py %*
    goto :check_error
)

if exist "%~dp0.env\Scripts\python.exe" (
    "%~dp0.env\Scripts\python.exe" main.py %*
    goto :check_error
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python main.py %*
    goto :check_error
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 main.py %*
    goto :check_error
)

echo [ERROR] Python environment not found!
echo Please run install.bat first to set up the environment.
pause
exit /b 1

:check_error
if %errorlevel% neq 0 (
    echo.
    echo Application exited with code %errorlevel%.
    pause
)
