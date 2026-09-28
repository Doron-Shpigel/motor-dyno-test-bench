# Changes Report — Milestone 1: Requirement 1 (R1) Serial Protocol Overhaul

**Agent**: Worker 1 (Implementer)  
**Date**: 2026-09-28  
**Scope**: `modules/serial_comm.py`, `tests/test_serial_comm.py`, `tests/__init__.py`

---

## 1. Summary of Changes

Milestone 1 updates the communication layer to support Phase 2 closed-loop PID control and telemetry streaming as implemented in Arduino firmware `dyno_controller.ino`.

### 1.1 `modules/serial_comm.py`
- **Updated Qt Signals**:
  - `data_received = pyqtSignal(float, float, int)`: Emits parsed `(torque_nm, speed_rpm, dac_raw)`.
  - `pid_received = pyqtSignal(float, float, float)`: Emits parsed `(kp, ki, kd)` gains.
  - `speed_received = pyqtSignal(int)`: Retained for backward compatibility; emits `int(round(speed))` on data packets.
  - `torque_received = pyqtSignal(float)`: Convenience signal emitting measured torque in N·m.
  - `dac_received = pyqtSignal(int)`: Convenience signal emitting current DAC output.
  - `ack_received = pyqtSignal(str)`: Emits command acknowledgment payload (e.g. `"START"`, `"SET_PID"`, `"SET_TORQUE:15.50"`, `"PONG"`).
  - `error_received = pyqtSignal(str)`: Emits error messages from Arduino or connection/parsing exceptions.
  - `connected = pyqtSignal()`: Emitted when port opens successfully.
  - `disconnected = pyqtSignal()`: Emitted when port closes.
  - `ready = pyqtSignal()`: Emitted when Arduino sends `DYNO_READY`.
  - `pong_received = pyqtSignal()`: Emitted when Arduino responds with `PONG`.

- **Testability & Dependency Injection**:
  - Added optional `boot_delay: float = 2.0` and `serial_factory: Any = serial.Serial` parameters to `SerialWorker.__init__`.
  - Allows unit tests to bypass the 2.0s hardware sleep and inject mock serial objects without modifying global state.

- **Outgoing Command Helper Methods**:
  - `send_start()`: Enqueues `"START"`.
  - `send_stop()`: Enqueues `"STOP"`.
  - `send_reset()`: Enqueues `"RESET"`.
  - `send_ping()`: Enqueues `"PING"`.
  - `send_get_pid()`: Enqueues `"<GET_PID>"`.
  - `send_set_pid(kp: float, ki: float, kd: float)`: Enqueues `f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"`.
  - `send_set_torque(torque_nm: float)`: Enqueues `f"<SET_TORQUE:{torque_nm:.2f}>"`.
  - Maintained generic `send_command(cmd: str)`.

- **Incoming Line Parsing (`_parse_line`)**:
  - Added parser for `<DATA:t,s,d>` emitting `data_received`, `speed_received`, `torque_received`, `dac_received`.
  - Added parser for `<PID_VALS:p,i,d>` emitting `pid_received`.
  - Added parser for `ACK:...` emitting `ack_received`.
  - Added parser for `PONG` emitting both `ack_received("PONG")` and `pong_received()`.
  - Added parser for `DYNO_READY` emitting `ready()`.
  - Added parser for `ERR:...` emitting `error_received`.
  - Maintained parser for legacy `SPEED:<val>` emitting `speed_received` and `data_received(0.0, float(val), 0)`.
  - Wrapped parsing in safe exception handling so malformed frames emit descriptive `error_received` messages without crashing the background thread.

### 1.2 `tests/__init__.py`
- Created package initialization for `tests` directory.

### 1.3 `tests/test_serial_comm.py`
- Implemented 29 automated unit tests across 5 test classes:
  - `TestSerialLineParser`: 15 tests covering standard data, zeros, integers, negative values, rounding behavior, PID values, small decimals, ACKs, PONG, DYNO_READY, errors, legacy speed, malformed data frames, malformed PID frames, and line noise/empty strings.
  - `TestSerialWorkerCommands`: 8 tests covering raw commands and all typed helper methods (`send_start`, `send_stop`, `send_reset`, `send_ping`, `send_get_pid`, `send_set_pid`, `send_set_torque`).
  - `TestSerialWorkerThread`: Full asynchronous thread lifecycle test with `MockSerial`, testing boot delay bypass, telemetry parsing, outgoing command queue processing, safety reset on disconnect, and port closure.
  - `TestSerialWorkerErrors`: 3 tests covering port open failure, runtime write failure, and runtime read failure.
  - `TestListSerialPorts`: 1 test verifying `list_serial_ports()` sorting with mocked serial comports.

---

## 2. Verification Summary
- `.env/bin/python -m unittest tests/test_serial_comm.py -v`: 29 tests passed, 0 failures, 0 errors.
- `.env/bin/python -m unittest discover tests -v`: 29 tests passed, 0 failures, 0 errors.
- Headless `MainWindow` instantiation check: Clean instantiation with no regressions.
