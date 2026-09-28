# Project: motor-dyno-test-bench Phase 2

## Architecture
- **Firmware (`arduino/dyno_controller/dyno_controller.ino`)**: Closed-loop PID controller driving MCP4725 DAC to apply torque brake. Emits `<DATA:t,s,d>` at 20 Hz, parses `<SET_TORQUE:t>`, `<GET_PID>`, `<SET_PID:p,i,d>`, `START`, `STOP`, `RESET`, `PING`.
- **Serial Layer (`modules/serial_comm.py`)**: `SerialWorker(QThread)` parses incoming serial messages from Arduino and emits Qt signals (`data_received`, `pid_received`, `ack_received`, `ready`, etc.).
- **Data Model (`modules/data_model.py`)**: Thread-safe storage for samples and test state (`Sample`, `DynoSession`, `RunState`).
- **Profile Engine (`modules/plf.py`)**: Interpolates target torque vs time from loaded CSV profile.
- **UI Components (`gui/`)**:
  - `pid_tuning_tab.py`: Read/write PID parameters to Arduino; set tolerance and settling time for PC stability monitor.
  - `control_panel.py`: Run controls and live telemetry readouts.
  - `main_window.py`: Orchestrator of GUI, closed-loop torque stepping, stability monitoring, data logging.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Serial Protocol Overhaul | `modules/serial_comm.py`, parsing `<DATA:t,s,d>`, `<PID_VALS:p,i,d>`, signals | none | DONE |
| 2 | PID Tuning UI Wiring | `gui/pid_tuning_tab.py`, read/write PID commands and parameter updates | Milestone 1 | DONE |
| 3 | Stability Monitor & Closed-Loop | `gui/main_window.py`, stability monitor, rolling buffer, setpoint gating | Milestones 1, 2 | DONE |
| 4 | E2E Integration & Verification | Full system test harness, stress testing, forensic audit | Milestones 1, 2, 3 | PLANNED |

## Interface Contracts

### `modules/serial_comm.py` ↔ Consumers (`main_window.py`, `pid_tuning_tab.py`)
- `SerialWorker.data_received(float, float, int)`: torque (N·m), speed (raw/RPM), dac (0-4095).
- `SerialWorker.pid_received(float, float, float)`: kp, ki, kd.
- `SerialWorker.ack_received(str)`: command acknowledgment text.
- `SerialWorker.ready()`: Arduino initialization complete (`DYNO_READY`).
- `SerialWorker.send_command(str)`: thread-safe method to queue commands. Outgoing commands include:
  - `START`, `STOP`, `RESET`, `PING`
  - `<GET_PID>`
  - `<SET_PID:kp,ki,kd>`
  - `<SET_TORQUE:torque_nm>`

### `gui/pid_tuning_tab.py` ↔ `gui/main_window.py`
- Signals/methods for PID communication:
  - `PidTuningTab.sig_read_pid` or direct `send_command("<GET_PID>")`.
  - `PidTuningTab.sig_set_pid(float, float, float)` or direct `send_command("<SET_PID:p,i,d>")`.
  - `PidTuningTab.sig_update_stability_params(float, float)`: tolerance (%), settling_time (s).
  - `PidTuningTab.set_stored_values(kp, ki, kd)`: updates read-only UI fields upon receiving PID values.
  - `PidTuningTab.set_stability_status(stable: bool)`: updates status badge (`STABLE` vs `WAITING`).

### `gui/main_window.py` ↔ `StabilityMonitor`
- `StabilityMonitor.add_reading(torque: float, timestamp: float)`: record measured torque reading.
- `StabilityMonitor.is_stable(target_torque: float) -> bool`: returns True if measured torque has remained within ±tolerance% of target_torque continuously for >= settling_time.
- `StabilityMonitor.set_parameters(tolerance_pct: float, settling_time_s: float)`: updates stability criteria.
- `StabilityMonitor.reset()`: clears buffer when stepping to a new setpoint.

## Code Layout
- `arduino/`: Arduino firmware sketches (`dyno_controller/dyno_controller.ino`).
- `gui/`: PyQt6 widgets and dialogs (`main_window.py`, `pid_tuning_tab.py`, `control_panel.py`, etc.).
- `modules/`: Backend logic and communication (`serial_comm.py`, `data_model.py`, `plf.py`, `csv_logger.py`).
- `tests/`: Automated unit, integration, and E2E test suites.
- `.agents/`: Coordination and orchestrator metadata.
