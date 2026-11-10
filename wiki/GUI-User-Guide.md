# Desktop GUI User Guide

The **motor-dyno-test-bench** desktop graphical interface is built with **PyQt6** and **pyqtgraph**, providing an interactive, OpenGL-accelerated control center for dynamometer testing, sensor calibration, and live graphing.

---

## 1. Launching the GUI

### Linux & macOS
Run the shell launcher from the repository root:
```bash
chmod +x run.sh
./run.sh
```

### Windows
Run the batch script:
```cmd
run.bat
```

> [!NOTE]
> The launcher scripts automatically inspect your environment, verify Python 3.11+, activate virtual environments (`.venv` or `.env`), and install required packages (`PyQt6`, `pyqtgraph`, `pyserial`, `numpy`) if they are missing.

---

## 2. Visual Layout Breakdown

The main window is organized with an adjustable horizontal splitter separating the left control stack from the right real-time plotting panel:

```
┌───────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│  Dyno Control Software                        │                                          [—] [口] [X]  │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ ┌─ [Control Panel] ── [Settings] ── [Telem] ┐ │ ┌─ [RPM & Torque vs Time] ──── [Dyno Curve (XY)] ───┐ │
│ │                                           │ │ │  RPM (RPM)                     Torque (N·m)       │ │
│ │  ▶ SERIAL CONNECTION                      │ │ │  3000 ┼───────────────────────────────┼ 5.0      │ │
│ │  Port: /dev/ttyUSB0   [ Connect ]         │ │ │       │         RPM (Blue)            │          │ │
│ │  Status: Connected (115200 baud)          │ │ │  2000 │        /‾‾‾‾‾‾‾‾‾‾\           │          │ │
│ │                                           │ │ │       │       /            \          │ 2.5      │ │
│ │  ▶ RUN MODE                               │ │ │  1000 │      /  Torque (Pink) \       │          │ │
│ │  Mode: [ Hybrid (Auto-Transition)  ▼ ]    │ │ │       │─────/──────────────────\──────┼ 0.0      │ │
│ │                                           │ │ │       0 ┴─────┴─────┴─────┴─────┴─────┴          │ │
│ │  ▶ TORQUE PROFILE                         │ │ │         0     10    20    30    40    50 Time(s)  │ │
│ │  [ Load CSV… ] example_profile.csv        │ │ └──────────────────────────────────────────────────┘ │
│ │  Points: 4 | Span: 0.00 to 4.50 N·m       │ │                                                      │
│ │  [ ▶ Start ]          [ ■ Stop ]          │ │                                                      │
│ │                                           │ │                                                      │
│ │  ▶ MANUAL TORQUE CONTROL                  │ │                                                      │
│ │  Target: [ 2.50 ] N·m                     │ │                                                      │
│ │  [====|=========================] 5.0 N·m │ │                                                      │
│ │  [ ▶ Start Manual ]   [ ■ Stop ]          │ │                                                      │
│ │                                           │ │                                                      │
│ │  ▶ HARDWARE RELAYS                        │ │                                                      │
│ │  [ Brake Power: ON  ]                     │ │                                                      │
│ │  [ Sensor Power: ON ]                     │ │                                                      │
│ │  [ Aux Relay: OFF   ]                     │ │                                                      │
│ │                                           │ │                                                      │
│ │  ▶ CSV LOGGING                            │ │                                                      │
│ │  Dir: /home/user/dyno_logs [ Browse ]     │ │                                                      │
│ │  [ Save Current Run Log ]                 │ │                                                      │
│ └───────────────────────────────────────────┘ │                                                      │
├───────────────────────────────────────────────┴────────────────────────────────────────────────────────┤
│ Ready. Telemetry: 2.49 N·m | 2750 RPM | DAC: 2048 | Settled: [ STABLE ]                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Left-Side Stack: Tab 1 — Control Panel

The **Control Panel** tab manages hardware connectivity, test lifecycle, setpoints, and relays.

### A. Serial Connection
1. Click **Connect**: A dialog displays all detected serial ports (e.g., `/dev/ttyUSB0`, `/dev/ttyACM0`, `COM3`).
2. Select your Arduino's port and confirm.
3. The status indicator changes to **Connected**, and the status bar reports firmware readiness (`DYNO_READY`).

### B. Operating Run Modes
Select the desired control strategy from the **Run Mode** dropdown:
- **Hybrid (Recommended)**: Starts in open-loop DAC mode when the motor is stopped ($\le 1.0\text{ RPM}$) to protect against integral windup. As soon as the motor spins up ($> 1.0\text{ RPM}$), it smoothly transitions to closed-loop hardware PID control.
- **Closed-Loop (PID)**: Arduino continuously modulates the MCP4725 DAC voltage based on load-cell feedback from analog pin A0 to strictly track the commanded torque setpoint.
- **Open-Loop (Manual DAC)**: Direct feed-forward control. Bypasses PID and maps torque setpoints directly to DAC register codes ($0$ to $4095$) based on calibration.

### C. Manual Torque Control
- **Target Torque Spinbox**: Enter any value between $0.00$ and your calibrated maximum torque.
- **Slider**: Drag to adjust torque dynamically in real time. Setpoints persist across runs so you do not need to re-enter values.
- **Start Manual / Stop**: Begins or ends an open-ended manual run.

### D. Automated Torque Profile
- **Load CSV…**: Opens the CSV Import Dialog (see [Section 6](#6-importing-torque-profiles)).
- **Profile Metadata**: Displays the number of profile steps, total test duration, and minimum/maximum torque setpoints.
- **Start Profile / Stop**: Begins the automated test sequence. The system holds each setpoint until the stability monitor confirms steady-state settling, then automatically steps to the next point.

### E. Hardware Relays
Three dedicated toggle buttons control bench sub-circuits via Arduino digital pins D2, D3, and D4:
- **Brake Relay (D2)**: Switches power to the HB-750M-2 hysteresis coil excitation supply.
- **Sensor Relay (D3)**: Powers the FYTH torque/speed transducer.
- **Aux Relay (D4)**: Auxiliary switch for cooling fans, DUT power contactors, or warning beacons.

> [!IMPORTANT]
> Whenever any test run is stopped (via **Stop**, an emergency condition, or serial disconnection), **all hardware relays are immediately opened** and the DAC is zeroed as a fail-safe measure.

---

## 4. Left-Side Stack: Tab 2 — Settings & Calibration

The **Settings** tab consolidates hardware PID tuning, stability thresholds, and sensor calibration.

```
┌─────────────────────────────────────────────────────────┐
│ Settings & Hardware Calibration                         │
├─────────────────────────────────────────────────────────┤
│ ▼ HARDWARE PID PARAMETERS (EEPROM)                      │
│   Active Gains:    Kp: 100.0000   Ki: 10.0000  Kd: 1.00 │
│   New Gains:       Kp: [120.00]   Ki: [12.00]  Kd: [1.5]│
│   [ Read from EEPROM ]          [ Write to EEPROM ]     │
├─────────────────────────────────────────────────────────┤
│ ▼ SOFTWARE STABILITY MONITOR                            │
│   Tolerance Band:    [ 2.0 ] %                          │
│   Settling Duration: [ 1.5 ] seconds                    │
│   Min Tolerance:     [ 0.10 ] N·m                       │
│   [ Apply Stability Settings ]                          │
├─────────────────────────────────────────────────────────┤
│ ▼ CALIBRATION & ENGINE PARAMETERS                       │
│   Max Torque:        [ 5.00 ] N·m                       │
│   RPM per ADC Count: [ 0.5000 ]                         │
│   Control Loop Tick: [ 100 ] ms                         │
│   [ Save Parameters ]                                   │
├─────────────────────────────────────────────────────────┤
│ ▼ MAX TORQUE CALIBRATION WIZARD                         │
│   Step 1: Power sensor and apply full DAC command (4095)│
│   [ 1. Start Calibration Force ]                        │
│   Step 2: Read peak ADC count and compute scale factor  │
│   [ 2. Finish & Calculate Scale ]                       │
└─────────────────────────────────────────────────────────┘
```

### 1. Hardware PID Parameters
- **Read from EEPROM**: Sends `<GET_PID>` to the Arduino. The current gains stored in the ATmega EEPROM populate the active readout.
- **Write to EEPROM**: Sends `<SET_PID:Kp,Ki,Kd>`. Values are written directly to EEPROM address 0 and survive board resets.

### 2. Software Stability Monitor
Configures when a torque step is considered "settled":
- **Tolerance Band (%)**: Permissible deviation from setpoint (default: $\pm 2.0\%$).
- **Settling Duration (s)**: Required continuous time within the band before advancing (default: $1.5\text{ s}$).
- **Minimum Tolerance Floor ($\text{N}\cdot\text{m}$)**: Absolute minimum tolerance applied near zero torque to prevent divide-by-zero or zero-width bands (default: $0.10\text{ N}\cdot\text{m}$).

### 3. Max Torque Calibration Wizard
Executes a guided calibration of the FYTH torque sensor:
1. Click **1. Start Calibration Force**: Powers the sensor relay and sets DAC to $4095$ (full excitation).
2. Manually apply full rated load ($5.0\text{ N}\cdot\text{m}$) using a calibrated lever arm or calibration weight.
3. Click **2. Finish & Calculate Scale**: Captures the peak ADC reading. If peak ADC exceeds zero-load baseline ($512$), the wizard updates:
   $$\text{torque\_per\_count} = \frac{5.0}{\text{peak\_adc} - 512.0}$$
   The new scale factor is instantly applied across all live calculations.

---

## 5. Left-Side Stack: Tab 3 — Telemetry Terminal

The **Telemetry** tab provides a real-time serial monitor displaying raw packets from the Arduino:
- Live streaming of `<DATA:torque,speed,dac>` frames at 20 Hz.
- Acknowledgment messages (`ACK:START`, `ACK:SET_TORQUE:2.50`).
- **Clear Button**: Wipes the active log buffer.
- **Save to File…**: Exports the terminal buffer to a raw `.txt` file for low-level protocol diagnostics.

---

## 6. Importing Torque Profiles

Clicking **Load CSV…** opens the modal **CSV Import Dialog**:

```
┌─────────────────────────────────────────────────────────┐
│ Import Torque Profile CSV                  [—] [口] [X] │
├─────────────────────────────────────────────────────────┤
│ CSV File: [/home/user/assets/example_profile.csv] [Browse]
│ Status: Valid profile (4 points, duration 60.0s)        │
│                                                         │
│ Preview:                                                │
│ ┌───────────────┬─────────────────────────────┐         │
│ │ time_s        │ torque_nm                   │         │
│ ├───────────────┼─────────────────────────────┤         │
│ │ 0.0           │ 0.0                         │         │
│ │ 5.0           │ 1.5                         │         │
│ │ 30.0          │ 4.5                         │         │
│ │ 60.0          │ 0.0                         │         │
│ └───────────────┴─────────────────────────────┘         │
│                                                         │
│                                  [ OK ]     [ Cancel ]  │
└─────────────────────────────────────────────────────────┘
```

### CSV Schema Requirements
The file must be a standard comma-separated text file with a header row:
```csv
time_s,torque_nm
0.0,0.0
5.0,1.25
15.0,2.50
30.0,4.00
45.0,0.0
```
- `time_s`: Elapsed time in seconds. **Must be strictly monotonically increasing** ($t_{i+1} > t_i$).
- `torque_nm`: Desired torque setpoint in $\text{N}\cdot\text{m}$.
- Minimum of 2 data rows required.

---

## 7. Real-Time Plotting Panel

The right panel features two high-performance **pyqtgraph** views rendered with anti-aliasing:

### Tab 1: RPM & Torque vs. Time (Dual Strip Chart)
- **Left Y-Axis (Blue)**: Shaft rotational speed in $\text{RPM}$.
- **Right Y-Axis (Pink)**: Measured torque in $\text{N}\cdot\text{m}$.
- **X-Axis**: Elapsed test time in seconds.
- Automatically pans and scrolls during live runs.

### Tab 2: Dyno Curve (XY Scatter & Trajectory)
- **X-Axis**: Measured Torque ($\text{N}\cdot\text{m}$).
- **Y-Axis**: Shaft Speed ($\text{RPM}$).
- Produces the classic motor torque-speed power curve, connecting data points in sequence.

> [!TIP]
> Both plot views support interactive mouse zoom (drag with right click), pan (drag with left click), and context menu export (right-click anywhere on the plot to export high-res PNG, SVG, or CSV).

---

## 8. GUI Troubleshooting Runbook

| Symptom | Cause | Solution |
|---|---|---|
| **Port list is empty in Connect Dialog** | Missing driver or user lacks permission | Ensure user is in `dialout` group: `sudo usermod -aG dialout $USER`. Check `dmesg \| tail` for USB device. |
| **"qt.qpa.xcb: could not connect to display"** | Running over SSH or headless without X11 forwarding | Use the curses Terminal UI (`./run_tui.sh`) or connect via `ssh -X`. |
| **Plots lag or stutter during long tests** | High sample buffer size | Plots decimate redraws automatically every 5 samples. You can also save and clear the session between multi-hour runs. |
| **Brake oscillates aggressively around setpoint** | PID gain $K_p$ or $K_i$ is too high | Switch to Settings tab. Reduce $K_p$ by 50% and $K_i$ by 75%, then write to EEPROM. |
