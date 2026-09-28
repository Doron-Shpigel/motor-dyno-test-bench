# Context and Technical Specification: Phase 2 Dyno Test Bench

## 1. System Architecture
The Motor Dyno Test Bench is a PyQt6 desktop application interfaced via USB Serial with an Arduino microcontroller running `dyno_controller.ino`.
- **Microcontroller**: Closed-loop PID controller reading torque (A0) and speed (A1), commanding an MCP4725 I2C DAC (0-4095) driving the dyno brake. Control loop runs at 50 Hz (20 ms); telemetry streams at 20 Hz (50 ms).
- **Desktop Application (PyQt6)**:
  - `modules/serial_comm.py`: `SerialWorker(QThread)` handling asynchronous serial I/O.
  - `gui/main_window.py`: Application coordinator, profile execution, data logging.
  - `gui/pid_tuning_tab.py`: UI for viewing/editing PID parameters in Arduino EEPROM and tuning stability parameters.
  - `modules/data_model.py`: Thread-safe session data store (`DynoSession`, `Sample`).
  - `modules/plf.py`: Profile interpolation.

## 2. Requirements Analysis

### R1. Serial Protocol Update (`modules/serial_comm.py`)
- **Incoming parsing**:
  - Telemetry format: `<DATA:torque,speed,dac>` (e.g., `<DATA:12.34,1500.00,2048>`).
  - Signal emission:
    - Emit `data_received(float, float, int)` containing `(torque, speed, dac)`.
    - Provide individual or backward-compatible signals if needed (`speed_received`, `torque_received`, `dac_received`).
  - PID settings format: `<PID_VALS:p,i,d>` (e.g., `<PID_VALS:100.0000,10.0000,1.0000>`).
    - Emit `pid_received(float, float, float)`.
  - Acknowledgment format: `ACK:...` (e.g. `ACK:START`, `ACK:STOP`, `ACK:RESET`, `ACK:SET_PID`, `ACK:SET_TORQUE:...`).
    - Emit `ack_received(str)`.
  - Ready signal: `DYNO_READY`.
    - Emit `ready()`.
  - Ping response: `PONG`.
    - Emit `ack_received("PONG")`.
- **Outgoing command generation**:
  - `START`, `STOP`, `RESET`, `PING`
  - `<GET_PID>`
  - `<SET_PID:p,i,d>`
  - `<SET_TORQUE:t>`

### R2. Stability Monitor (`gui/main_window.py`)
- **Remove open-loop torque-to-DAC math**:
  - Old: `dac_raw = int(min(max(torque_nm / max_torque_nm, 0.0), 1.0) * 4095)`, sending `SET:<dac>`.
  - New: PC commands closed-loop torque setpoint via `<SET_TORQUE:torque_nm>`.
- **Stability Monitor / Rolling Buffer**:
  - Accumulates incoming torque telemetry in a rolling buffer or time window.
  - Evaluates whether physical measured torque is within specified tolerance (e.g., ±2% or configurable %) of current setpoint.
  - Must remain within tolerance continuously for the specified settling duration (e.g. 1.5 seconds) before advancing to the next setpoint in the profile.
  - UI feedback: update `PidTuningTab` status badge (`STABLE` vs `WAITING`).
  - Data logging & plotting: accurately log measured torque, speed/RPM, and reported DAC from `<DATA:t,s,d>` telemetry.

### R3. Wire PID UI to Serial Commands (`gui/pid_tuning_tab.py`)
- Connect "Read from Arduino" (`_on_read_from_arduino`) -> sends `<GET_PID>`.
- Wire incoming `<PID_VALS:p,i,d>` to update stored values display via `set_stored_values(kp, ki, kd)`.
- Connect "Save to Arduino" (`_on_save_to_arduino`) -> validates inputs, formats `<SET_PID:p,i,d>`, sends to Arduino.
- Connect "Update Software Parameters" (`_on_update_software_params`) -> passes tolerance and settling time to MainWindow's stability monitor.
- Provide clean connection mechanism between `PidTuningTab` and `SerialWorker` / `MainWindow`.

## 3. Verification Criteria
1. `modules/serial_comm.py` unit and integration tests parsing `<DATA:t,s,d>`, `<PID_VALS:p,i,d>`, `ACK:...`, `DYNO_READY`, `PONG`.
2. `gui/pid_tuning_tab.py` test verifying button actions send `<GET_PID>`, properly format `<SET_PID:p,i,d>`, update software params, and populate UI on `pid_received`.
3. `gui/main_window.py` test verifying stability monitor rolling buffer: profile holds until torque stabilizes within tolerance for settling time, then advances; verifying removal of open-loop math.
4. Comprehensive end-to-end integration test exercising all components together.
