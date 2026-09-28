## 2026-09-28T13:38:00Z
You are Worker 2 (Implementer) for Milestone 1 remediation of the motor-dyno-test-bench project.

Your assigned working directory is:
/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone1_2/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context:
Milestone 1 implemented the Serial Protocol Overhaul, but independent adversarial testing by Challengers and Reviewers identified two critical defects in `modules/serial_comm.py`:
1. CRITICAL Concurrency Defect in `SerialWorker`: Calling `stop()` during the `_boot_delay` window causes `self._running = True` to overwrite the stop request when sleep finishes. The thread runs indefinitely and hangs `worker.wait()`.
2. Partial Signal Emission on `NaN`/`Inf`: In `_parse_line`, `data_received.emit(torque, speed, dac)` was called before `int(round(speed))` which raises `ValueError` on NaN. Corrupt data was emitted before an error was raised, and other signals were skipped.

Remediation Tasks in `modules/serial_comm.py`:
1. Fix thread lifecycle in `SerialWorker`:
   - In `__init__`, add `self._stop_requested = False` (or use a `threading.Event`).
   - In `stop()`, set `self._stop_requested = True` and `self._running = False`.
   - In `run()`:
     - Make `_boot_delay` interruptible:
       ```python
       end_time = time.monotonic() + self._boot_delay
       while time.monotonic() < end_time:
           if self._stop_requested or not self._running:
               return
           time.sleep(0.05)
       ```
     - Guard loop entry: if `self._stop_requested or not self._running`, return immediately (which triggers the `finally:` block and emits `disconnected`).
     - Only set `self._running = True` and emit `connected.emit()` if `not self._stop_requested`.
2. Fix atomicity and validation in `_parse_line()`:
   - Call `line = line.strip()` at the start.
   - For `<DATA:t,s,d>`:
     - Check `import math; if not (math.isfinite(torque) and math.isfinite(speed)): raise ValueError("Non-finite numeric values in DATA frame")`.
     - Calculate `speed_int = int(round(speed))`.
     - Only AFTER all fields are verified and computed without exception, emit the signals:
       `self.data_received.emit(torque, speed, dac)`
       `self.speed_received.emit(speed_int)`
       `self.torque_received.emit(torque)`
       `self.dac_received.emit(dac)`
   - For `<PID_VALS:p,i,d>`:
     - Check `if not (math.isfinite(kp) and math.isfinite(ki) and math.isfinite(kd)): raise ValueError("Non-finite values in PID frame")`.
     - Only then emit `self.pid_received.emit(kp, ki, kd)`.
3. Verification:
   - Run: `.env/bin/python -m unittest tests/test_serial_comm.py -v`
   - Run: `.env/bin/python -m unittest tests/test_serial_adversarial.py -v`
   - Run: `.env/bin/python -m unittest tests/test_adversarial_boundary.py -v`
   - Verify all test suites pass with 0 failures and 0 errors!
   - Verify GUI instantiation: `QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('OK')"`

Deliverables:
- Write `changes.md` and `handoff.md` in:
  /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone1_2/
- Send a completion message to the orchestrator.
