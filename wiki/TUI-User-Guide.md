# Terminal User Interface (TUI) Guide

The **motor-dyno-test-bench** Terminal User Interface (TUI) is an interactive, full-featured console application built using Python's standard library `curses` module (`modules/tui.py`). It exposes 100% of the dynamometer's hardware and software capabilities without requiring a desktop window manager, X11, Wayland, or graphical libraries.

---

## 1. Why Use the TUI?

The TUI is the ideal operational interface for:
- **Embedded & Single-Board Computers**: Raspberry Pi 3/4/5, BeagleBone, Odroid, or NVIDIA Jetson boards mounted directly on the dynamometer frame.
- **Headless Linux Servers**: Systems running stripped server OS installations without X11/Qt libraries.
- **Remote SSH Sessions**: Low-bandwidth field diagnostics or automated long-duration testing over cellular or local network tunnels.
- **Fast Startup & Minimal Resource Footprint**: Launches instantly with zero dependency overhead.

---

## 2. Launching the TUI

Launch using the dedicated launcher scripts or python:

### Linux / macOS / Raspberry Pi
```bash
# Launch interactive TUI (auto-detects virtual environment)
./run_tui.sh

# Launch directly specifying port
./run_tui.sh --port /dev/ttyUSB0

# Launch in Demonstration / Offline Simulation mode
./run_tui.sh --demo
```

### Windows Command Prompt / PowerShell
```cmd
:: Launch interactive TUI
run_tui.bat

:: Launch in demo mode
run_tui.bat --demo
```

### Command-Line Arguments
```
usage: tui.py [-h] [--port PORT] [--baud BAUD] [--demo] [--profile PROFILE]

Motor Dyno Test Bench - Terminal User Interface (TUI)

options:
  -h, --help         show this help message and exit
  --port PORT        Serial port device name (e.g. /dev/ttyUSB0, COM3)
  --baud BAUD        Serial communication baudrate (default: 115200)
  --demo, --mock     Run in demonstration mode with physics simulation
  --profile PROFILE  Path to CSV load profile to auto-stage on launch
```

---

## 3. Visual Dashboard Architecture

The terminal display automatically adjusts to terminal dimensions (minimum recommended: $80 \times 24$ characters):

```
┌──────────────────────── MOTOR DYNO TEST BENCH [TUI] ─────────────────────────┐
│ STATUS: CONNECTED [/dev/ttyUSB0 @ 115200]  |  MODE: HYBRID  |  STATE: RUNNING │
├──────────────────────────────────────────────────────────────────────────────┤
│ MEASURED TORQUE :   2.48 N·m       TARGET SETPOINT   :   2.50 N·m            │
│ SHAFT SPEED     : 2748.2 RPM       COMMANDED DAC     : 2048 / 4095           │
│ SPEED ADC RAW   :    549 cts       STABILITY BADGE   : [ STABLE ]            │
│ HARDWARE RELAYS : [1] BRAKE: ON    [2] SENSOR: ON    [3] AUX: OFF            │
├──────────────────────────────────────────────────────────────────────────────┤
│ TORQUE HISTORY (*=Measured, -=Target, X=Match)               Max: 5.0 N·m    │
│  5.0┤                                                                        │
│     │                                                                        │
│  2.5┤ ------------------------XXXXXXXXXXXXXXX-----------------------------   │
│     │                        *****************                               │
│  0.0┴──────────────────────────────────────────────────────────────────────  │
├──────────────────────────────────────────────────────────────────────────────┤
│ EVENT LOG (Last 5 events)                                                    │
│ [14:22:01] INFO  Transport connected to /dev/ttyUSB0.                        │
│ [14:22:03] INFO  Arduino ready. Active gains: Kp=100.0, Ki=10.0, Kd=1.0      │
│ [14:22:10] INFO  Relay BRAKE set to ON.                                      │
│ [14:22:15] INFO  Manual Run started. Setpoint: 2.50 N·m.                     │
│ [14:22:18] INFO  Torque settled within ±2.0% for 1.5s -> System STABLE.      │
├──────────────────────────────────────────────────────────────────────────────┤
│ COMMANDS: [C]onn [M]anual [P]rofile [S]top [R]eset [O]Mode [1/2/3]Relays     │
│           [+/-]Adj [T]unePID [K]Calib [L]og [Q]uit                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Keyboard Controls Cheat-Sheet

All actions are triggered by single keystrokes (case-insensitive unless noted):

| Key | Action | Behavior & Prompts |
|:---:|---|---|
| **`[C]`** | **Connect / Disconnect** | Opens port selection prompt. If connected, prompts `Disconnect? [y/N]`. |
| **`[M]`** | **Manual Test Run** | Prompts for target torque ($\text{N}\cdot\text{m}$) and starts manual loading. |
| **`[+]`** | **Increment Setpoint** | Increases target torque by $+0.10\text{ N}\cdot\text{m}$ in real time. |
| **`[-]`** | **Decrement Setpoint** | Decreases target torque by $-0.10\text{ N}\cdot\text{m}$ in real time. |
| **`[P]`** | **Profile Test Run** | Prompts for CSV path (e.g. `assets/example_profile.csv`) and starts automated sequence. |
| **`[S]`** | **Emergency STOP** | **Immediate safety trip**: zeroes DAC, opens all relays, stops logging, sets `FINISHED`. |
| **`[R]`** | **Reset Dyno** | Resets session sample buffers, zeroes sensors, and sets state to `IDLE`. |
| **`[O]`** | **Cycle Control Mode** | Cycles through `HYBRID` $\rightarrow$ `CLOSED_LOOP` $\rightarrow$ `OPEN_LOOP`. |
| **`[1]`** | **Toggle Brake Relay** | Toggles digital output D2 controlling brake excitation power. |
| **`[2]`** | **Toggle Sensor Relay** | Toggles digital output D3 powering FYTH torque/speed transducer. |
| **`[3]`** | **Toggle Aux Relay** | Toggles digital output D4 for auxiliary bench equipment or fans. |
| **`[T]`** | **Tune PID Gains** | Prompts for `Kp, Ki, Kd` (comma-separated) and burns them to Arduino EEPROM. |
| **`[K]`** | **Torque Calibration** | Toggles 2-step calibration wizard: energizes sensor for force application, then calculates scale factor. |
| **`[L]`** | **Toggle CSV Logging** | If logging, flushes and saves file; if idle, prompts for target CSV filepath. |
| **`[Q]`** | **Clean Quit** | Safely shuts down engine, turns off relays, restores terminal state, and exits. |

---

## 5. Real-Time ASCII Torque History Chart

The center region displays an oscilloscope-style strip-chart tracking torque versus target setpoint over time:

### Features & Legend
- **Dynamic Y-Axis Scaling**: Automatically scales the vertical range based on recent peak torque with rounding for clear tick intervals ($0.0$, $2.5$, $5.0\text{ N}\cdot\text{m}$).
- **Measured Torque (`*`, Cyan)**: Real-time calibrated torque from sensor feedback.
- **Target Setpoint (`-`, Yellow)**: Active commanded target torque setpoint.
- **Coincidence Match (`X`, Green)**: Highlighted when measured torque matches setpoint within tolerance band.
- **Horizontal Baseline (`┴`, Gray)**: Zero-torque reference axis.

```
│  5.0┤                                                  │
│  2.5┤ -------------XXXXXXXXXXXXXXX--------------------  │
│  0.0┴───────────────────────────────────────────────── │
```

---

## 6. Interactive Modal Input Prompts

When you press an action key (such as `[C]`, `[M]`, `[P]`, `[T]`, or `[L]`), the bottom command bar transforms into an interactive modal input prompt:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Target torque in N·m [2.50]: 3.25█                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Prompt Interaction Features
- **Default Suggestions**: Current values or standard file paths are presented inside brackets `[...]`. Simply press **Enter** to accept the default.
- **Inline Editing**: Supports typing, **Backspace**, and character insertion up to 256 characters.
- **Escape Cancellation**: Pressing **Escape** cancels the prompt immediately without altering state.
- **Horizontal Scrolling**: If the prompt or input exceeds terminal width, the prompt text scrolls horizontally to keep the cursor visible.

---

## 7. Demonstration & Simulation Mode (`--demo`)

When hardware is not connected, the TUI includes a full **SimulatedTransport** physics engine.

```bash
./run_tui.sh --demo
```

### What the Simulation Emulates:
1. **Motor Startup & Droop**: Emulates motor acceleration up to $2800\text{ RPM}$ with realistic speed sag under mechanical braking load:
   $$\text{RPM} = \max(400.0, 2800.0 - (\tau_{\text{load}} \times 100.0))$$
2. **Torque Settling Dynamics**: Smoothly ramps measured torque toward setpoint with simulated physical inertia and sensor noise.
3. **Stability Transitions**: The `[ STABLE ]` badge turns green when settled and clears when adjusting setpoints via `[+]` and `[-]`.
4. **Relay & Calibration Verification**: Simulates peak ADC readings (~$930$ counts) during the `[K]` calibration wizard.

---

## 8. Remote SSH & Terminal Resizing

### Running Over SSH
The TUI is fully compatible with standard SSH connections:
```bash
ssh -t user@bench-pi.local "./motor-dyno-test-bench/run_tui.sh"
```
The `-t` flag forces pseudo-terminal allocation, ensuring curses initializes properly.

### Window Resizing (`KEY_RESIZE`)
If you resize your terminal window or change display orientation:
- The curses event loop traps `curses.KEY_RESIZE`.
- The screen buffer is erased and completely recalculated to fit the new row/column dimensions.
- The ASCII chart adjusts its width to match the new column count.
- Minimum recommended size is $80\times 24$. On smaller terminals, lower log entries are clipped to protect telemetry readouts.
