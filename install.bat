@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo   Motor Dyno Test Bench - Windows Installer
echo ====================================================

cd /d "%~dp0"

:: 1. Detect Python (try python first, then py -3)
set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python 3 was not detected on your system.
    echo Please download and install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo IMPORTANT: Make sure to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VER=%%i"
echo [OK] Detected host Python: %PY_VER%

:: 2. Check for venv capability and create virtual environment
set "VENV_DIR=%~dp0.venv"
if not exist "%VENV_DIR%" (
    echo Creating virtual environment in .venv ...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Verify that Python venv is installed and not blocked by permissions or antivirus.
        pause
        exit /b 1
    )
) else (
    echo Using existing virtual environment in .venv ...
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment python executable not found at:
    echo   %VENV_PYTHON%
    pause
    exit /b 1
)

:: 3. Upgrade pip, setuptools, wheel
echo Upgrading pip, setuptools, wheel...
"%VENV_PYTHON%" -m pip install --upgrade pip wheel setuptools --quiet

:: 4. Install dependencies from requirements.txt
if exist "%~dp0requirements.txt" (
    echo Installing dependencies from requirements.txt...
    "%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. Check your internet connection.
        pause
        exit /b 1
    )
) else (
    echo [ERROR] requirements.txt not found!
    pause
    exit /b 1
)

:: 5. Verification test
echo Running verification test...
"%VENV_PYTHON%" -c "import PyQt6, serial, pyqtgraph, numpy; from modules.engine import DynoEngine; print('OK')" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Verification check encountered an issue.
    echo Please verify Visual C++ Redistributable or graphics drivers if PyQt6 failed.
) else (
    echo [OK] Verification passed: Core modules and GUI backend loaded successfully.
)

:: 6. Success banner
echo.
echo ====================================================
echo   Installation Complete! Ready to Run.
echo ====================================================
echo You can launch Motor Dyno Test Bench using:
echo   GUI Mode:    run.bat
echo   TUI Mode:    run_tui.bat
echo   Test Suite:  .venv\Scripts\pytest.exe
echo.
pause
exit /b 0
