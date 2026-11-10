# Installation and Troubleshooting Guide

This guide provides end-to-end instructions for installing, configuring, and verifying the **motor-dyno-test-bench** software on Linux and Windows workstations, as well as on embedded Linux targets such as the Raspberry Pi.

---

## 1. System Requirements

### Hardware Requirements
- **PC / SBC:** Any x86_64 PC (Windows 10/11, Ubuntu 20.04+, Debian 11+, Fedora, Arch) or ARM64/ARMv7 Single Board Computer (Raspberry Pi 3/4/5 running Raspberry Pi OS).
- **RAM:** Minimum 512 MB (TUI mode) or 2 GB (PyQt6 GUI mode).
- **USB:** At least one available USB 2.0/3.0 port for Arduino connection.

### Software Requirements
- **Python:** Version **3.11** or newer.
- **Microcontroller Tooling:** Arduino IDE 1.8.x / 2.x or `arduino-cli` (to flash the controller firmware).

---

## 2. Dependency Matrix

The project separates core functionality from optional GUI presentation layers:

| Package | Version | Required For | Purpose |
|---|---|:---:|---|
| **`python`** | $\ge 3.11$ | **All** | Runtime environment |
| **`pyserial`** | $\ge 3.5$ | **All** | Low-level USB serial communication |
| **`numpy`** | $\ge 1.24$ | **All** | Fast linear interpolation in PLF & numeric arrays |
| **`curses`** | Standard Library | **TUI** | Terminal user interface on Linux/macOS/POSIX |
| **`windows-curses`** | $\ge 2.3$ (Win only) | **TUI** | Windows standard library emulation for curses |
| **`PyQt6`** | $\ge 6.5$ | **GUI** | Desktop graphical interface widgets & event loop |
| **`pyqtgraph`** | $\ge 0.13$ | **GUI** | Real-time OpenGL-accelerated strip charts and dyno curves |
| **`pytest`** | $\ge 7.0$ | **Development** | Running test suite and CI verification |

---

## 3. Installation Guide: Linux & Raspberry Pi

### Step 1: Clone Repository
```bash
git clone https://github.com/doron/motor-dyno-test-bench.git
cd motor-dyno-test-bench
```

### Step 2: Configure Serial Port Permissions (`dialout` group)
On Linux systems, access to USB serial devices (`/dev/ttyUSB*` or `/dev/ttyACM*`) is restricted to members of the `dialout` (or `uucp`) group.
```bash
# Add your user to the dialout group
sudo usermod -aG dialout $USER

# Log out and log back in, or activate group in current shell:
newgrp dialout
```
Verify your user membership:
```bash
groups | grep dialout
```

### Step 3: Zero-Sudo Local Virtual Environment Setup
You do not need root access to set up the Python environment:
```bash
# Create local virtualenv
python3 -m venv .venv

# Activate virtualenv
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install pyqtgraph PyQt6 pytest
```

### Step 4: Launch Applications
```bash
# Launch Desktop GUI
./run.sh

# Or launch Terminal Interface (TUI)
./run_tui.sh
```

---

## 4. Installation Guide: Windows

### Option A: Automated One-Click Batch Script
Double-click `run.bat` (for GUI) or `run_tui.bat` (for TUI). The scripts will check for an active Python installation, create `.venv` if absent, install requirements, and start the application.

### Option B: Manual Setup (PowerShell or Command Prompt)
1. Open PowerShell or Command Prompt in the repository folder:
   ```powershell
   cd motor-dyno-test-bench
   ```
2. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install pyqtgraph PyQt6 windows-curses pytest
   ```
4. Launch:
   ```powershell
   python main.py      # Desktop GUI
   python tui.py       # Terminal TUI
   ```

---

## 5. Microcontroller Firmware Flashing

1. Connect your Arduino Uno or Nano via USB cable.
2. Open the Arduino IDE.
3. Open `arduino/dyno_controller/dyno_controller.ino`.
4. Ensure the custom library at `arduino/dyno_controller/MCP4725example/lib/mcp4725` is accessible in your Arduino `libraries` folder or specified via CLI.
5. Select **Tools $\rightarrow$ Board $\rightarrow$ Arduino Uno** (or Nano).
6. Select the appropriate serial port.
7. Click **Upload**.
8. Verify upload success in Serial Monitor at `115200` baud: you should see `DYNO_READY`.

---

## 6. Comprehensive Troubleshooting Guide

### Issue 1: "Permission denied: '/dev/ttyUSB0'" or "Port not found"
- **Cause:** User account lacks read/write permissions for Linux serial devices, or device driver is missing.
- **Solution:**
  1. Add user to `dialout`: `sudo usermod -aG dialout $USER` and log back in.
  2. Check system log when plugging in board: `dmesg | tail -n 20`. Look for `ch341-uart` or `cdc_acm`.
  3. On Debian/Ubuntu with BRLTTY installed, the braille display service may grab CH340 devices. Uninstall BRLTTY if not used:
     ```bash
     sudo apt remove brltty
     ```

---

### Issue 2: "qt.qpa.xcb: could not connect to display"
- **Cause:** Attempting to run `main.py` in a headless environment, over standard SSH without X11 forwarding, or on a system without a display server.
- **Solution:**
  1. Use the curses Terminal User Interface (`./run_tui.sh` or `python tui.py`), which has zero graphical requirements.
  2. If you need the GUI over SSH, connect with trusted X11 forwarding: `ssh -X user@host`.

---

### Issue 3: "DAC_INIT_ERR: 0x20" or DAC Failure on Startup
- **Cause:** Arduino cannot communicate with the MCP4725 DAC over I²C.
- **Solution:**
  1. Verify wiring: SDA to Arduino A4 (Uno/Nano), SCL to Arduino A5.
  2. Check I²C address: Default code expects `0x60` (ADDR pin tied to GND). If ADDR is connected to 5V, the address is `0x61`. Change `#define MCP4725_ADDR 0x61` in `dyno_controller.ino`.
  3. Ensure I²C pull-up resistors ($4.7\text{ k}\Omega$) are present between SDA/SCL and 5V.

---

### Issue 4: Aggressive PID Torque Hunting / Violent Oscillations
- **Cause:** Controller gains are poorly tuned for the mechanical inertia and magnetic response of the setup.
- **Solution:**
  1. Open the **Settings Tab** (or press `[T]` in TUI).
  2. Set $K_i = 0$ and $K_d = 0$.
  3. Start with a modest proportional gain ($K_p = 50.0$).
  4. Gradually increase $K_p$ until torque reaches ~90% of setpoint without violent overshoot.
  5. Introduce small integral gain ($K_i = 5.0$) to eliminate steady-state error.
  6. Introduce derivative gain ($K_d = 0.5$ to $1.5$) to dampen approach oscillations.

---

### Issue 5: CSV Load Profile Fails to Import
- **Cause:** Malformed CSV structure or non-monotonic timestamps.
- **Solution:**
  - Verify exact header row: `time_s,torque_nm`.
  - Ensure every value in `time_s` is strictly greater than the preceding row ($t_{i+1} > t_i$).
  - Avoid trailing empty lines or text comments in the CSV file.
