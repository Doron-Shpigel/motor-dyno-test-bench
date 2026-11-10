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
    echo "Please ensure Python 3 is installed."
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" --version 2>&1)
echo -e "${GREEN}✓ Found host Python:${NC} $PY_VERSION ($PYTHON_BIN)"

# Helper: download a URL to a target file using Python's built-in urllib (zero curl/wget dependency)
download_file() {
    local url="$1"
    local dest="$2"
    "$PYTHON_BIN" -c "
import urllib.request, sys
try:
    urllib.request.urlretrieve(sys.argv[1], sys.argv[2])
    sys.exit(0)
except Exception as e:
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)
" "$url" "$dest" 2>/dev/null || \
    curl -sSL "$url" -o "$dest" 2>/dev/null || \
    wget -qO "$dest" "$url" 2>/dev/null
}

# 2. Virtual environment setup
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

# If an incomplete or corrupt .venv exists without a python binary, wipe it
if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_PY" ]; then
    echo -e "${YELLOW}Detected broken .venv directory. Rebuilding...${NC}"
    rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
    echo -e "${BLUE}Creating isolated virtual environment in:${NC} $VENV_DIR"
    # Try 1: Standard venv
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null; then
        # Try 2: venv --without-pip (works on Debian/Ubuntu even when python3-venv is missing!)
        echo -e "${YELLOW}Notice: Standard venv creation failed (Debian/Ubuntu ensurepip stripped).${NC}"
        echo -e "${BLUE}Creating venv using --without-pip (zero sudo)...${NC}"
        if ! "$PYTHON_BIN" -m venv --without-pip "$VENV_DIR" 2>/dev/null; then
            # Try 3: PyPA standalone virtualenv.pyz zipapp
            echo -e "${YELLOW}Notice: Standard venv module not present. Downloading standalone virtualenv...${NC}"
            VENV_PYZ="/tmp/virtualenv_$$.pyz"
            download_file "https://bootstrap.pypa.io/virtualenv.pyz" "$VENV_PYZ"
            if [ -f "$VENV_PYZ" ]; then
                "$PYTHON_BIN" "$VENV_PYZ" "$VENV_DIR" --quiet
                rm -f "$VENV_PYZ"
            else
                echo -e "${RED}[ERROR] Failed to create virtual environment.${NC}"
                exit 1
            fi
        fi
    fi
else
    echo -e "${BLUE}Using existing virtual environment in:${NC} $VENV_DIR"
fi

if [ ! -f "$VENV_PY" ]; then
    echo -e "${RED}[ERROR] Virtual environment python binary not found at $VENV_PY${NC}"
    exit 1
fi

# 3. Ensure pip exists inside .venv (auto-bootstrap if missing)
if ! "$VENV_PY" -m pip --version &>/dev/null; then
    echo -e "${YELLOW}Notice: 'pip' is not present in .venv.${NC}"
    echo -e "${BLUE}Automatically bootstrapping standalone 'pip' into .venv (no sudo required)...${NC}"
    GET_PIP="/tmp/get_pip_$$.py"
    download_file "https://bootstrap.pypa.io/get-pip.py" "$GET_PIP"
    if [ -f "$GET_PIP" ]; then
        "$VENV_PY" "$GET_PIP" --quiet --no-warn-script-location
        rm -f "$GET_PIP"
        echo -e "${GREEN}✓ Successfully bootstrapped pip into .venv!${NC}"
    else
        echo -e "${RED}[ERROR] Could not download get-pip.py. Please check your internet connection.${NC}"
        exit 1
    fi
fi

# 4. Upgrade pip, wheel, setuptools inside venv
echo -e "${BLUE}Updating pip, setuptools, and wheel in .venv...${NC}"
"$VENV_PY" -m pip install --upgrade pip wheel setuptools --quiet --no-warn-script-location

# 5. Install requirements.txt
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo -e "${BLUE}Installing required dependencies (PyQt6, pyqtgraph, pyserial, numpy, pytest)...${NC}"
    "$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements.txt" --no-warn-script-location
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
echo -e "${BLUE}Running verification test...${NC}"

# Auto-load bundled X11 libraries (libxcb-cursor0) so GUI verifies with zero sudo
if [[ "$(uname)" == "Linux" ]]; then
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64)  LIB_ARCH_DIR="$SCRIPT_DIR/libs/x86_64" ;;
        aarch64|arm64) LIB_ARCH_DIR="$SCRIPT_DIR/libs/aarch64" ;;
        *)             LIB_ARCH_DIR="" ;;
    esac
    if [ -n "$LIB_ARCH_DIR" ] && [ -d "$LIB_ARCH_DIR" ]; then
        export LD_LIBRARY_PATH="$LIB_ARCH_DIR:${LD_LIBRARY_PATH:-}"
        echo -e "${GREEN}✓ Bundled zero-sudo Linux libraries active:${NC} $LIB_ARCH_DIR"
    fi
fi

if "$VENV_PY" -c "import serial, numpy; from modules.engine import DynoEngine; print('OK')" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Core engine & serial drivers verified successfully!${NC}"
else
    echo -e "${RED}[ERROR] Core engine verification failed.${NC}"
    exit 1
fi

# GUI verification (informative only)
if QT_QPA_PLATFORM=offscreen "$VENV_PY" -c "import PyQt6, pyqtgraph; print('OK')" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Desktop GUI backend (PyQt6 & pyqtgraph) verified successfully!${NC}"
else
    echo -e "${YELLOW}ℹ Note: GUI libraries (libEGL/libGL) not found on host. Terminal UI (TUI) and Headless API will run 100% fine.${NC}"
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
