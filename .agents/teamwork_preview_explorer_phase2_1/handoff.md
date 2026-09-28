# Handoff Report: Requirement 1 (R1) Serial Protocol Overhaul

**Agent**: Explorer 1 (Serial Protocol Explorer)  
**Recipient**: Orchestrator / Implementer 1  
**Date**: 2026-09-28  
**Working Directory**: `/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/teamwork_preview_explorer_phase2_1/`  
**Reference Document**: `analysis.md` in this directory  

---

## 1. Observation

1. **Arduino Firmware (`arduino/dyno_controller/dyno_controller.ino`)**:
   - Baud rate configured at line 8: `#define SERIAL_BAUD 115200`.
   - Setup emits boot notification at line 73: `Serial.println(F("DYNO_READY"));`.
   - 20 Hz PC telemetry streaming loop at lines 134–143:
     ```cpp
     if (now - lastTelemetryTime >= TELEMETRY_INTERVAL) {
       lastTelemetryTime = now;
       Serial.print("<DATA:");
       Serial.print(currentTorque, 2); Serial.print(",");
       Serial.print(currentSpeed, 2); Serial.print(",");
       Serial.print(dacValue);
       Serial.println(">");
     }
     ```
     `currentTorque` is float (line 92), `currentSpeed` is float (line 93), `dacValue` is integer `0-4095` (line 28).
   - Serial parser `handleSerialCommands()` lines 149–159 reads incoming characters until newline `\n`.
   - `processCommand(cmd)` lines 162–211 handles:
     - `START` -> sets `isRunning = true; Serial.println("ACK:START");` (line 168-170).
     - `STOP` / `RESET` -> sets `isRunning = false; targetTorque = 0.0; errorIntegral = 0.0; mcp4725_write(0); Serial.print("ACK:"); Serial.println(cmd);` (lines 171-177).
     - `PING` -> `Serial.println("PONG");` (lines 178-180).
     - `<GET_PID>` -> `Serial.print("<PID_VALS:"); Serial.print(pid.Kp, 4); ... Serial.println(">");` (lines 182-187).
     - `<SET_PID:p,i,d>` -> updates `pid` struct in EEPROM and replies `Serial.println("ACK:SET_PID");` (lines 189-202).
     - `<SET_TORQUE:t>` -> sets `targetTorque` and replies `Serial.print("ACK:SET_TORQUE:"); Serial.println(targetTorque);` (lines 204-210).
     - Notice: Open-loop `SET:<dac>` is **absent** from `processCommand`.

2. **Current Python Serial Worker (`modules/serial_comm.py`)**:
   - Class `SerialWorker(QThread)` lines 40–155.
   - Defined signals (lines 48–53):
     `speed_received = pyqtSignal(int)`, `ack_received = pyqtSignal(str)`, `error_received = pyqtSignal(str)`, `connected = pyqtSignal()`, `disconnected = pyqtSignal()`, `ready = pyqtSignal()`.
   - Line parser `_parse_line` (lines 137–155) only handles `SPEED:<int>`, `ACK:<cmd>`, `ERR:<msg>`, `PONG`, `DYNO_READY`. It lacks `<DATA:t,s,d>` and `<PID_VALS:p,i,d>`.
   - Run loop (line 91) has hardcoded `time.sleep(2.0)` upon opening serial port.

3. **Current GUI Call Sites (`gui/main_window.py`)**:
   - Line 258: `self._worker.speed_received.connect(self._on_speed_received)`
   - Lines 290–292:
     ```python
     @pyqtSlot(int)
     def _on_speed_received(self, adc_val: int) -> None:
         self._last_adc = adc_val
     ```
   - Expects `speed_received` to emit an integer representation of speed/ADC count.

4. **Test Environment & Execution**:
   - Python virtual environment: `/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.env/bin/python` (Python 3.11).
   - Package audit via pip: `PyQt6 6.11.0`, `pyqtgraph 0.14.0`, `pyserial 3.5`, `numpy 2.4.6`.
   - Pytest is not installed in the environment (`ModuleNotFoundError: No module named 'pytest'`), whereas Python standard library `unittest` is fully operational (`python -m unittest`).
   - Headless Qt validation: Running `.env/bin/python` with `QCoreApplication` and mock serial execution succeeded without requiring an X11 server or physical COM port.

---

## 2. Logic Chain

1. **Protocol Synchronization**:
   - From (1), the Arduino firmware emits `<DATA:t,s,d>` where `t` is float, `s` is float, and `d` is int. It also emits `<PID_VALS:p,i,d>` where `p`, `i`, `d` are floats.
   - Therefore, `SerialWorker` must emit `data_received = pyqtSignal(float, float, int)` and `pid_received = pyqtSignal(float, float, float)`.
   - Because `dyno_controller.ino` outputs `<DATA:t,s,d>`, the parser in `_parse_line` must split on commas, strip brackets, and safely convert types inside a `try...except (ValueError, IndexError)` block to prevent crashing on corrupt bytes.

2. **Backward Compatibility Preservation**:
   - From (3), `MainWindow` explicitly connects `self._worker.speed_received.connect(self._on_speed_received)` and expects an `int`.
   - If `speed_received` were removed or changed to `float` during Milestone 1, `main_window.py` would fail before Milestone 3 is reached.
   - Therefore, when `<DATA:t,s,d>` is received, `SerialWorker` must emit `self.data_received.emit(torque, speed, dac)` AND `self.speed_received.emit(int(round(speed)))`. This maintains 100% backward compatibility for Milestone 1.

3. **Command Interface Completeness**:
   - From (1), Arduino firmware requires `<SET_TORQUE:t>`, `<SET_PID:p,i,d>`, `<GET_PID>`, `START`, `STOP`, `RESET`, `PING`.
   - To eliminate formatting bugs in UI callers, `SerialWorker` should provide typed helper methods (`send_set_torque()`, `send_set_pid()`, `send_get_pid()`, `send_start()`, `send_stop()`, `send_reset()`, `send_ping()`) while retaining generic `send_command(cmd)`.

4. **Testability Without Hardware**:
   - From (2), `SerialWorker.run()` contains `time.sleep(2.0)` and directly constructs `serial.Serial()`.
   - By adding optional arguments `boot_delay: float = 2.0` and `serial_factory: Callable = serial.Serial` to `SerialWorker.__init__`, unit tests can pass `boot_delay=0.0` and a mock `FakeSerial` object.
   - This allows instant, deterministic test execution with standard `unittest` without physical hardware or timeouts.

---

## 3. Caveats

1. **Closed-Loop Setpoint vs Open-Loop DAC**:
   - The Arduino firmware ignores `SET:<dac>`. While Milestone 1 updates the serial layer to provide `send_set_torque()`, `main_window.py` still issues `SET:<dac>` in its control loop tick (line 221). Full closed-loop operation will only take effect once Milestone 3 refactors `main_window.py`.
2. **Speed Scaling Units**:
   - In `dyno_controller.ino` line 93, `currentSpeed` is read via `analogRead(SPEED_PIN)`, which is an ADC count (`0-1023`). In `MainWindow`, `rpm_per_count` converts this count to RPM. If the Arduino firmware is later updated to calculate RPM onboard, `rpm_per_count` calibration in `CalibrationSettings` may need adjusting.
3. **PyQt6 Event Loop in Unit Tests**:
   - Because `SerialWorker` is a `QThread`, cross-thread signal delivery from `run()` to the main thread is queued. Unit tests exercising the full worker thread must call `QCoreApplication.instance().processEvents()` to process dispatched signals. Synchronous parser tests on `_parse_line` do not require this.

---

## 4. Conclusion

1. Requirement 1 (R1) is fully specified and ready for implementation by Implementer 1.
2. `modules/serial_comm.py` requires:
   - Defining signals: `data_received(float, float, int)`, `pid_received(float, float, float)`, `pong_received()`, along with existing `speed_received(int)`, `ack_received(str)`, `error_received(str)`, `connected()`, `disconnected()`, `ready()`.
   - Updating `_parse_line` to parse `<DATA:t,s,d>`, `<PID_VALS:p,i,d>`, `ACK:...`, `PONG`, `DYNO_READY`, `ERR:...`, and legacy `SPEED:...`.
   - Emitting both `data_received(torque, speed, dac)` and `speed_received(int(round(speed)))` on telemetry frames.
   - Adding typed outgoing helper methods: `send_start()`, `send_stop()`, `send_reset()`, `send_ping()`, `send_get_pid()`, `send_set_pid(kp, ki, kd)`, `send_set_torque(torque_nm)`.
   - Adding `boot_delay=2.0` and `serial_factory=serial.Serial` to `__init__` for test injection.
3. A comprehensive test suite should be placed at `tests/test_serial_comm.py` utilizing Python's built-in `unittest` runner.

---

## 5. Verification Method

Independent verification of R1 can be executed as follows:

1. **Inspect Code Files**:
   - Review `modules/serial_comm.py` against the specifications in `analysis.md` section 6.
   - Verify that all signal signatures and `_parse_line` match `dyno_controller.ino`.

2. **Run Automated Test Suite**:
   Execute the unit test suite covering line parsing, command queueing, and headless thread execution:
   ```bash
   .env/bin/python -m unittest discover tests -v
   ```

3. **Verify Existing Application Launch**:
   Ensure GUI launches without regression:
   ```bash
   QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('MainWindow instantiated cleanly!')"
   ```

4. **Invalidation Conditions**:
   - `data_received` fails to emit `(float, float, int)` on `<DATA:12.34,1500.0,2048>`.
   - `pid_received` fails to emit `(float, float, float)` on `<PID_VALS:100.0,10.0,1.0>`.
   - `speed_received` is broken or fails to emit integer speed, breaking `MainWindow`.
   - Malformed frames cause unhandled exceptions that crash the thread.
