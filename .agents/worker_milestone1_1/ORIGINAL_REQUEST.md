## 2026-09-28T13:27:24Z

You are Worker 1 (Implementer) for Milestone 1 of the motor-dyno-test-bench project.

Your assigned working directory is:
/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone1_1/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Scope:
Implement Milestone 1: Requirement 1 (R1) - Serial Protocol Overhaul in `modules/serial_comm.py` and write comprehensive automated unit tests in `tests/test_serial_comm.py`.

Authoritative references:
- Explorer 1 Analysis: /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/teamwork_preview_explorer_phase2_1/analysis.md
- Explorer 1 Handoff: /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/teamwork_preview_explorer_phase2_1/handoff.md
- Arduino Firmware: /home/doron/Links/GitHub Folder/motor-dyno-test-bench/arduino/dyno_controller/dyno_controller.ino
- Existing serial module: /home/doron/Links/GitHub Folder/motor-dyno-test-bench/modules/serial_comm.py

Implementation Requirements:
1. Update `modules/serial_comm.py`:
   - Qt Signals in `SerialWorker`:
     - `data_received = pyqtSignal(float, float, int)`  # (torque, speed, dac)
     - `pid_received = pyqtSignal(float, float, float)` # (kp, ki, kd)
     - `speed_received = pyqtSignal(int)`               # kept for backward compatibility; emits int(round(speed)) on data
     - `ack_received = pyqtSignal(str)`                 # acknowledged command string
     - `error_received = pyqtSignal(str)`               # error messages
     - `connected = pyqtSignal()`
     - `disconnected = pyqtSignal()`
     - `ready = pyqtSignal()`                           # DYNO_READY received
     - `pong_received = pyqtSignal()`                   # PONG received (and/or ack_received.emit("PONG"))
   - Outgoing helper methods:
     - `send_start()` -> queues "START"
     - `send_stop()` -> queues "STOP"
     - `send_reset()` -> queues "RESET"
     - `send_ping()` -> queues "PING"
     - `send_get_pid()` -> queues "<GET_PID>"
     - `send_set_pid(kp: float, ki: float, kd: float)` -> queues f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"
     - `send_set_torque(torque_nm: float)` -> queues f"<SET_TORQUE:{torque_nm:.2f}>"
     - `send_command(cmd: str)` -> existing generic queueing method
   - Incoming Line Parsing in `_parse_line(self, line: str)`:
     - Handle `<DATA:t,s,d>` (e.g. `<DATA:12.34,1500.00,2048>`): parse torque, speed, dac; emit `data_received(torque, speed, dac)` AND `speed_received(int(round(speed)))`.
     - Handle `<PID_VALS:p,i,d>` (e.g. `<PID_VALS:100.0000,10.0000,1.0000>`): parse p, i, d; emit `pid_received(p, i, d)`.
     - Handle `ACK:...`: emit `ack_received(...)`.
     - Handle `DYNO_READY`: emit `ready()`.
     - Handle `PONG`: emit `ack_received("PONG")` and `pong_received()`.
     - Handle `ERR:...`: emit `error_received(...)`.
     - Handle legacy `SPEED:...`: emit `speed_received(val)`.
     - Wrap line parsing in safe try/except so malformed serial data emits `error_received` and never crashes the worker thread.
   - Testability:
     - Add `boot_delay: float = 2.0` and `serial_factory: Any = serial.Serial` parameters to `SerialWorker.__init__` with defaults so unit tests can pass `boot_delay=0.0` and mock serial objects.
2. Create `tests/test_serial_comm.py`:
   - Unit tests covering:
     - Parsing `<DATA:t,s,d>` (standard, floats, integers, zeroes, negative values)
     - Signal emissions (`data_received` and `speed_received`)
     - Parsing `<PID_VALS:p,i,d>` and `pid_received` emission
     - Parsing `ACK:START`, `ACK:SET_PID`, `ACK:SET_TORQUE:...`, `DYNO_READY`, `PONG`, `ERR:...`
     - Malformed input handling (corrupt brackets, non-numeric values, missing fields)
     - Outgoing command helpers (`send_start`, `send_stop`, `send_get_pid`, `send_set_pid`, `send_set_torque`)
     - Thread lifecycle and queueing with a mock serial device.
3. Verification:
   - Run tests using: `.env/bin/python -m unittest tests/test_serial_comm.py -v`
   - Verify all tests pass with 0 failures and 0 errors.
   - Verify `MainWindow` still instantiates cleanly without regressions:
     `QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('MainWindow instantiation OK')"`

Deliverables:
- Write `changes.md` and `handoff.md` in:
  /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone1_1/
- In `handoff.md`, document the exact build/test commands executed and their output.
- Send a message back to the orchestrator when complete.
