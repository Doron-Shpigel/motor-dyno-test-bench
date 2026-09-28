# motor-dyno-test-bench

A cross-platform (Windows + Linux) dynamometer test bench project and control application built with **Python 3**, **PyQt6**, and **Arduino**.

## Main hardware

- Arduino (DAC/ADC bridge between the PC GUI and bench hardware)
- DFR0552 I2C 12-bit DAC module
- FYTH-5-5000-K torque and speed sensor (5 Nm)
- HB-750M-2 hysteresis brake (5 Nm)
- 5251-2 current regulated power supply

---

## Features

| Feature | Detail |
|---|---|
| Torque profile | Load a CSV → Piecewise Linear Function → interpolated setpoints |
| DAC control | Sends I²C commands to **MCP4725** via Arduino (USB/serial) |
| Speed reading | Reads Arduino analog input (A0) → converts to RPM |
| Real-time plot | RPM & Torque vs Time strip chart + classic Dyno Curve (RPM vs N·m) |
| CSV logging | Auto-timestamped log file: `elapsed_s, torque_nm, rpm, dac_raw, adc_raw` |
| Calibration | Configurable max torque, RPM/count scale factor, tick rate, output dir |

---

## Requirements

- Python 3.11+
- Arduino IDE (to flash the firmware)
- MCP4725 breakout board wired to Arduino SDA/SCL

### Python packages (auto-installed by the launcher scripts)

```
PyQt6
pyqtgraph
pyserial
numpy
```

---

## Quick Start

### 1 — Flash the Arduino

Open `arduino/dyno_controller/dyno_controller.ino` in the Arduino IDE and upload it to your board.

Default pin assignments (edit the `#define` block at the top of the sketch to change):

| Signal | Arduino pin |
|---|---|
| MCP4725 SDA | A4 (Uno/Nano) |
| MCP4725 SCL | A5 (Uno/Nano) |
| Speed sensor | A0 |
| Status LED | 13 |

The MCP4725 I²C address is **0x60** (ADDR pin to GND).  
Change `MCP4725_ADDR` to `0x61` if your ADDR pin is tied HIGH.

### 2 — Prepare a torque-profile CSV

The CSV must have a header row with exactly these two columns:

```
time_s,torque_nm
0.0,0.0
5.0,10.0
30.0,40.0
60.0,0.0
```

- `time_s` — seconds from test start (must be **strictly increasing**)
- `torque_nm` — desired torque setpoint in Newton·metres

An example is included at `assets/example_profile.csv`.

### 3 — Launch

**Windows:**
```
run.bat
```
or
```
conda env create --prefix .env -f environment.yml
conda activate .\.env
python main.py
```

**Linux / macOS:**
```bash
chmod +x run.sh && ./run.sh
```
> **Linux note:** Serial port access requires the `dialout` group.  
> The launcher script adds you automatically; log out and back in once.

---

## Calibration

Open **⚙ Calibration / Settings** from the control panel:

| Setting | Meaning |
|---|---|
| **Max torque (N·m)** | Torque value that maps to DAC=4095 (full voltage). Measure your brake's max rating. |
| **RPM per ADC count** | `RPM = ADC_raw × this_factor`. Spin the motor at a known RPM and read the ADC value to derive it. |
| **Tick interval** | How often the control loop fires (ms). 100 ms = 10 Hz. |
| **Output directory** | Where timestamped log CSVs are saved. |

### DAC → Voltage → Torque

```
DAC_value = clamp(torque_nm / max_torque_nm, 0, 1) × 4095
Vout      = (DAC_value / 4095) × Vcc          (Vcc = 3.3 V or 5 V)
Brake     = Vout controls hysteresis current
```

---

## Project Layout

```
.
├── main.py                        # Entry point
├── environment.yml                # Conda environment definition
├── requirements.txt
├── run.bat                        # Windows one-click launcher
├── run.sh                         # Linux/macOS one-click launcher
├── assets/
│   └── example_profile.csv        # Sample torque profile
├── modules/
│   ├── plf.py                     # Piecewise Linear Function (CSV → interpolator)
│   ├── serial_comm.py             # Arduino serial thread (QThread)
│   ├── data_model.py              # Thread-safe session / sample model
│   └── csv_logger.py              # Auto-timestamped CSV writer
├── gui/
│   ├── main_window.py             # Main window + control loop
│   ├── control_panel.py           # Left-hand control/status panel
│   ├── plot_widget.py             # pyqtgraph real-time plots
│   ├── calibration_dialog.py      # Calibration settings dialog
│   ├── csv_import_dialog.py       # Torque-profile CSV importer
│   └── serial_config_dialog.py    # Serial port selector
└── arduino/
    └── dyno_controller/
        └── dyno_controller.ino    # Arduino firmware
```

---

## Serial Protocol Reference

All messages are ASCII, newline-terminated (`\n`), at **115200 baud**.

| Direction | Message | Meaning |
|---|---|---|
| PC → Arduino | `SET:<0-4095>` | Set MCP4725 DAC value |
| PC → Arduino | `START` | Begin streaming speed readings |
| PC → Arduino | `STOP` | Stop streaming |
| PC → Arduino | `PING` | Connectivity check |
| PC → Arduino | `RESET` | Set DAC=0 and stop streaming |
| Arduino → PC | `SPEED:<0-1023>` | Raw ADC reading from A0 |
| Arduino → PC | `ACK:<cmd>` | Command acknowledged |
| Arduino → PC | `ERR:<msg>` | Error message |
| Arduino → PC | `PONG` | Response to PING |
| Arduino → PC | `DYNO_READY` | Firmware booted successfully |

---

## Extending the Software

All modules are independent and import each other only through well-defined interfaces:

- **New sensor** → add a new serial message type in `serial_comm.py` and a new column in `csv_logger.py`.
- **Different DAC** → replace only the `SET:` command path in `serial_comm.py` and the Arduino sketch.
- **Power calculation** → add `power_kw = torque_nm × rpm × 2π / 60` inside the control loop tick in `main_window.py` and expose it in `data_model.py`.
- **C++ port** → the protocol and CSV format are language-agnostic; replace the Python layer with a Qt/C++ app calling the same Arduino firmware.

---

## License and credit

This project is licensed under the **MIT License** (see `LICENSE`).

You are free to use, modify, and distribute the GUI software and Arduino code without asking permission, as long as the license notice is preserved.

If you use this project, please provide credit to **Doron Shpigel** in your documentation, presentation, or project notes.
