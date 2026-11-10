#!/usr/bin/env bash
# =============================================================================
# Dyno Control Software — Linux / macOS GUI Launcher
# Usage: ./run.sh [--debug]
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Serial port access reminder for Linux dialout group
if [[ "$(uname)" == "Linux" ]]; then
    CURRENT_USER="${USER:-$(whoami)}"
    if ! (id -nG "$CURRENT_USER" 2>/dev/null || groups "$CURRENT_USER" 2>/dev/null) | grep -qw dialout; then
        echo "NOTE: User '$CURRENT_USER' is not in the 'dialout' group."
        echo "      Hardware serial ports may require dialout permissions."
        echo "      Run: sudo usermod -aG dialout $CURRENT_USER"
    fi
fi

# Locate Python in order of precedence:
# 1. Local .venv
# 2. Local .env virtualenv / conda prefix
# 3. Conda environment if available
# 4. System python3
PYTHON_BIN=""

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.env/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.env/bin/python"
elif command -v conda &> /dev/null && [ -d "$SCRIPT_DIR/.env" ]; then
    CONDA_BASE=$(conda info --base 2>/dev/null || true)
    if [ -n "$CONDA_BASE" ] && [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
        conda activate "$SCRIPT_DIR/.env" 2>/dev/null || true
        PYTHON_BIN="python"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    if command -v python3 &>/dev/null; then
        PYTHON_BIN="python3"
    elif command -v python &>/dev/null; then
        PYTHON_BIN="python"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: No suitable Python environment found."
    echo "Please run ./install.sh to create a virtual environment and install dependencies."
    exit 1
fi

if [[ "${1:-}" == "--debug" ]]; then
    echo "Running Dyno Control in foreground (debug mode)..."
    exec "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@"
else
    echo "Running Dyno Control in background. Terminal will close."
    nohup "$PYTHON_BIN" "$SCRIPT_DIR/main.py" "$@" >/dev/null 2>&1 &
fi
