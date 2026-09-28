#!/usr/bin/env bash
# Dyno Control Software — Linux / macOS launcher
# Usage:  chmod +x run.sh && ./run.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer python3
PYTHON=$(command -v python3 2>/dev/null || command -v python)

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3 not found. Install python3 via your package manager."
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(sys.version_info.major * 10 + sys.version_info.minor)")
if (( PY_VER < 311 )); then
    echo "ERROR: Python 3.11+ required (found $("$PYTHON" --version))."
    exit 1
fi

# Install / upgrade requirements
echo "Checking dependencies…"
"$PYTHON" -m pip install -q --upgrade pip
"$PYTHON" -m pip install -q -r requirements.txt

# Linux: serial port access requires the user to be in the 'dialout' group.
# If not already a member, add and remind the user to re-login.
if [[ "$(uname)" == "Linux" ]]; then
    if ! groups "$USER" | grep -qw dialout; then
        echo ""
        echo "NOTE: Adding '$USER' to 'dialout' group for serial port access."
        echo "      You will need to LOG OUT and LOG IN again for this to take effect."
        sudo usermod -aG dialout "$USER" 2>/dev/null || true
    fi
fi

echo "Starting Dyno Control Software…"
"$PYTHON" main.py
