#!/usr/bin/env bash
# Dyno Control Software — Linux / macOS launcher
# Usage:  chmod +x run.sh && ./run.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v conda &> /dev/null; then
    echo "ERROR: Conda is not installed or not in PATH."
    echo "Please download and install Miniconda or Anaconda:"
    echo "https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

if [ ! -d ".env" ]; then
    echo "ERROR: Conda environment '.env' not found in the project directory."
    echo "Please run: conda env create --prefix .env -f environment.yml"
    exit 1
fi

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

echo "Activating Conda environment and starting Dyno Control Software…"
CONDA_BASE=$(conda info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate ./.env

if [[ "${1:-}" == "--debug" ]]; then
    echo "Running in debug mode. Terminal will stay open."
    python main.py --debug
else
    echo "Running in background. Terminal will close."
    nohup python main.py >/dev/null 2>&1 &
fi
