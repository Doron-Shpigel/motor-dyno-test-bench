@echo off
setlocal

:: =============================================================================
:: Dyno Control Software — Windows TUI Launcher
:: =============================================================================
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" tui.py %*
    goto :check_error
)

if exist "%~dp0.env\Scripts\python.exe" (
    "%~dp0.env\Scripts\python.exe" tui.py %*
    goto :check_error
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python tui.py %*
    goto :check_error
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 tui.py %*
    goto :check_error
)

echo [ERROR] Python environment not found!
echo Please run install.bat first to set up the environment.
pause
exit /b 1

:check_error
if %errorlevel% neq 0 (
    echo.
    echo TUI exited with code %errorlevel%.
    pause
)
