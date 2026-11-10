#!/usr/bin/env bash
# =============================================================================
# Motor Dyno Test Bench — Standalone Linux/macOS Installer
# =============================================================================
# Sets up a local isolated virtual environment (.venv) and installs
# all required dependencies in user space. Does NOT require sudo.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI styling
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BOLD}${BLUE}====================================================${NC}"
echo -e "${BOLD}${BLUE}  Motor Dyno Test Bench — Installer${NC}"
echo -e "${BOLD}${BLUE}====================================================${NC}"

# 1. Detect Python 3
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    if python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
        PYTHON_BIN="python"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[ERROR] Python 3 was not found on your system.${NC}"
    echo "Please install Python 3.10+ using your package manager:"
    echo "  Debian/Ubuntu: sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
    echo "  Arch Linux:    sudo pacman -S python python-pip"
    echo "  macOS:         brew install python3"
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" --version 2>&1)
echo -e "${GREEN}✓ Found host Python:${NC} $PY_VERSION ($PYTHON_BIN)"

# 2. Check for venv module
if ! "$PYTHON_BIN" -m venv --help &>/dev/null; then
    echo -e "${RED}[ERROR] The Python 'venv' module is missing.${NC}"
    echo "On Debian/Ubuntu systems, install it with:"
    echo -e "  ${YELLOW}sudo apt update && sudo apt install python3-venv${NC}"
    echo "Alternatively, you can use Conda or virtualenv."
    exit 1
fi

# 3. Create or reuse virtual environment
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${BLUE}Creating virtual environment in:${NC} $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo -e "${BLUE}Using existing virtual environment in:${NC} $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -f "$VENV_PY" ]; then
    echo -e "${RED}[ERROR] Virtual environment python binary not found at $VENV_PY${NC}"
    exit 1
fi

# 4. Upgrade pip, wheel, setuptools inside venv
echo -e "${BLUE}Upgrading pip, setuptools, and wheel in .venv...${NC}"
"$VENV_PY" -m pip install --upgrade pip wheel setuptools --quiet

# 5. Install requirements.txt
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo -e "${BLUE}Installing dependencies from requirements.txt...${NC}"
    "$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements.txt"
else
    echo -e "${RED}[ERROR] requirements.txt not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# 6. Check serial port permissions on Linux (dialout group)
if [[ "$(uname)" == "Linux" ]]; then
    CURRENT_USER="${USER:-$(whoami)}"
    if (id -nG "$CURRENT_USER" 2>/dev/null || groups "$CURRENT_USER" 2>/dev/null) | grep -qw "dialout"; then
        echo -e "${GREEN}✓ Serial permissions:${NC} '$CURRENT_USER' is in 'dialout' group."
    else
        echo -e "${YELLOW}NOTE: To access hardware serial ports, add yourself to dialout:${NC}"
        echo -e "      ${BOLD}sudo usermod -aG dialout $CURRENT_USER${NC}"
        echo -e "      (You will need to log out and log back in for this to take effect)."
    fi
fi

# 7. Verification check
echo -e "${BLUE}Running headless verification test...${NC}"
if QT_QPA_PLATFORM=offscreen "$VENV_PY" -c "import PyQt6, serial, pyqtgraph, numpy; from modules.engine import DynoEngine; print('OK')" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Verification passed: Core modules & GUI backend load cleanly.${NC}"
else
    echo -e "${YELLOW}[WARNING] Headless import check failed. Please verify GUI libraries (libegl/libgl) if on Linux.${NC}"
fi

# 8. Success banner
echo ""
echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}  Installation Complete! Ready to Run.${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "You can launch Motor Dyno Test Bench using:"
echo -e "  ${BOLD}GUI Mode:${NC}   ./run.sh       (or ./run.sh --debug)"
echo -e "  ${BOLD}TUI Mode:${NC}   ./run_tui.sh   (e.g. ./run_tui.sh --demo)"
echo -e "  ${BOLD}Test Suite:${NC} .venv/bin/pytest"
echo ""
