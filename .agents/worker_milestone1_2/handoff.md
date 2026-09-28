# Handoff Report — Milestone 1 Remediation (Worker 2)

## 1. Observation
Before remediation, running adversarial test suites revealed critical concurrency and parsing vulnerabilities:
- Command: `.env/bin/python -m unittest tests/test_serial_adversarial.py -v`
  Verbatim failures:
  ```text
  FAIL: test_CRITICAL_early_stop_during_boot_delay_race_condition
  AssertionError: CRITICAL CONCURRENCY BUG CONFIRMED: worker.stop() was called during boot_delay, but self._running was reset to True at line 151, causing worker to ignore stop()!
  
  FAIL: test_immediate_stop_after_start_race_condition
  AssertionError: CRITICAL CONCURRENCY BUG CONFIRMED: worker.stop() immediately after start() was overwritten by self._running = True!
  ```
- Command: `.env/bin/python -m unittest tests/test_adversarial_boundary.py -v`
  Verbatim failure:
  ```text
  FAIL: test_stop_during_boot_delay_race_condition
  AssertionError: False is not true : VULNERABILITY CONFIRMED: Calling stop() during boot_delay was overwritten by self._running = True, thread failed to exit!
  ```
- In `modules/serial_comm.py` (lines 143-152 prior to fix):
  - `time.sleep(self._boot_delay)` blocked the thread unconditionally.
  - Calling `worker.stop()` during this sleep set `self._running = False`, but upon waking up, `self._running = True` was executed blindly, resetting the stop request and deadlocking `worker.wait()`.
  - In `_parse_line()` (lines 213-216 prior to fix):
    `self.data_received.emit(torque, speed, dac)` was emitted before `int(round(speed))`. When `speed` was `NaN`, `round(speed)` raised `ValueError`, resulting in partial signal emission where corrupt telemetry was broadcast before an error was recorded.

## 2. Logic Chain
1. **Thread Concurrency**: By adding `self._stop_requested = False` in `SerialWorker.__init__`, updating `stop()` to set both `self._stop_requested = True` and `self._running = False`, and converting `_boot_delay` into a 50ms polling loop checking `self._stop_requested or not self._running`, early stop requests are detected within 50ms without blocking.
2. **Loop Entry & Teardown**: Enclosing the connection phase within `try ... finally:` ensures that if `self._stop_requested` is true at any point during connection or boot delay, `run()` exits immediately. The `finally:` block executes safely zeroing the DAC (`RESET\n`), closing the port, and emitting `disconnected.emit()`.
3. **Atomic Parsing & Finite Float Validation**:
   - `line = line.strip()` is called at the start of `_parse_line()`, trimming extraneous whitespace.
   - In `<DATA:t,s,d>`, `math.isfinite(torque) and math.isfinite(speed)` is enforced. If either is non-finite (`NaN`, `Inf`, `-Inf`), a `ValueError("Non-finite numeric values in DATA frame")` is raised before any signal is emitted.
   - `speed_int = int(round(speed))` is calculated before signal dispatch.
   - Signals `data_received`, `speed_received`, `torque_received`, and `dac_received` are emitted strictly after all parsing and calculations succeed, preventing partial signal emission.
   - In `<PID_VALS:p,i,d>`, `math.isfinite(kp) and math.isfinite(ki) and math.isfinite(kd)` is enforced before emitting `pid_received`.
4. **Adversarial Assertion Alignment**: Adversarial test suites originally created to document the buggy behavior were updated to assert proper atomic rejection of non-finite values and whitespace handling, and verified to achieve 100% pass rates.

## 3. Caveats
- No caveats. All 3 test suites pass completely with 0 failures and 0 errors across 83 total test cases.

## 4. Conclusion
Both identified defects in `modules/serial_comm.py` have been completely resolved using minimal, genuine code modifications. Concurrency lifecycle handling in `SerialWorker` is robust against early and immediate stops, and frame parsing in `_parse_line` guarantees atomicity and finite numeric validation.

## 5. Verification Method
Run the following verification commands from the project root:

1. Standard unit tests:
   ```bash
   .env/bin/python -m unittest tests/test_serial_comm.py -v
   ```
   Expected output: `Ran 29 tests ... OK`

2. Adversarial stress & concurrency tests:
   ```bash
   .env/bin/python -m unittest tests/test_serial_adversarial.py -v
   ```
   Expected output: `Ran 20 tests ... OK`

3. Boundary & malformed packet tests:
   ```bash
   .env/bin/python -m unittest tests/test_adversarial_boundary.py -v
   ```
   Expected output: `Ran 34 tests ... OK`

4. Offscreen GUI instantiation:
   ```bash
   QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('OK')"
   ```
   Expected output: `OK`
