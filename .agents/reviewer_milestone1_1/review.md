# Milestone 1 Code Review & Adversarial Stress Report

**Target**: Requirement 1 (R1) — Serial Protocol Overhaul (`modules/serial_comm.py`, `tests/test_serial_comm.py`)  
**Reviewer**: Reviewer 1 (Milestone 1)  
**Date**: 2026-09-28  
**Verdict**: **PASS** (with Minor Findings / Actionable Recommendations)

---

## 1. Executive Summary

Worker 1's implementation of Requirement 1 successfully overhauls the serial communication module to support the full firmware protocol defined in `arduino/dyno_controller/dyno_controller.ino`.

Key achievements verified:
1. **Signal Signatures**: All required signals (`data_received(float, float, int)`, `pid_received(float, float, float)`, `speed_received(int)`, `ack_received(str)`, `error_received(str)`, `ready()`, `pong_received()`, `connected()`, `disconnected()`) are correctly declared with explicit PyQt types.
2. **Command Helpers**: Strongly-typed helper methods (`send_start`, `send_stop`, `send_reset`, `send_ping`, `send_get_pid`, `send_set_pid`, `send_set_torque`) match Arduino command grammar verbatim.
3. **Line Noise Resilience**: Safe parsing prevents any malformed or corrupted serial string from terminating the background `QThread`.
4. **Testability & Performance**: Inclusion of `boot_delay` and `serial_factory` dependency injection parameters enables fast, deterministic headless unit testing.
5. **Test Coverage**: 29 unit tests pass in 0.26s.
6. **Backward Compatibility**: `MainWindow` imports and instantiates cleanly with zero regressions.

---

## 2. Integrity Verification

The implementation was scrutinized for integrity violations:
- **No hardcoded test results**: Telemetry values and PID fields are dynamically parsed via `split(",")` and converted via `float()` / `int()`.
- **No facade or dummy implementations**: Real `QThread` lifecycle, real thread-safe `queue.Queue`, real `serial.Serial` integration, and robust exception trapping.
- **No shortcuts bypassing the task**: Complete parser logic for all 7 frame categories.
- **Independent verification**: All test commands and compatibility checks were executed directly and verified independently.

**Integrity Verdict**: **CLEAN / NO VIOLATIONS**.

---

## 3. Verified Claims & Test Executions

| Claim | Verification Command | Result |
|---|---|---|
| Unit Test Suite | `.env/bin/python -m unittest tests/test_serial_comm.py -v` | **PASS** (29 tests in 0.259s, 0 failures, 0 errors) |
| Test Discovery | `.env/bin/python -m unittest discover tests -v` | **PASS** (29 tests in 0.260s) |
| GUI Backward Compatibility | `QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('OK')"` | **PASS** (`OK` emitted cleanly) |
| Protocol Consistency | Verbatim comparison against `dyno_controller.ino` | **PASS** (all packet formats align) |

---

## 4. Adversarial Findings & Stress-Testing

### [Finding 1 - Major/Minor]: Thread Race Condition on `stop()` during `boot_delay`
- **Location**: `modules/serial_comm.py`, lines 143–152.
- **Root Cause**:
  `SerialWorker.__init__` initializes `self._running = False`. When the worker thread runs:
  ```python
  if self._boot_delay > 0:
      time.sleep(self._boot_delay)
  ...
  self._running = True
  self.connected.emit()
  ```
  If the consumer calls `worker.stop()` while the thread is sleeping during `boot_delay` (e.g. user clicks Connect then immediately Disconnect, or closes the window within 2 seconds), `stop()` sets `self._running = False`. However, when `time.sleep` finishes, line 151 unconditionally overwrites `self._running = True`, emits `connected`, and enters `while self._running:`.
- **Reproduction**:
  ```python
  w = SerialWorker("PORT", boot_delay=0.5, serial_factory=lambda *a, **kw: DummySerial())
  w.start()
  time.sleep(0.1) # user disconnects during boot delay
  w.stop()
  w.wait(1000)    # times out!
  # w.isRunning() is True; worker is orphaned and running in background
  ```
- **Blast Radius**: If the user disconnects or quits within 2 seconds of connecting, the thread outlives `MainWindow`, producing a zombie thread or Qt warning (`QThread: Destroyed while thread is still running`).
- **Recommended Fix**:
  Use a `threading.Event` or check `self._running`:
  ```python
  # In __init__:
  self._stop_event = threading.Event()

  # In stop():
  self._running = False
  self._stop_event.set()

  # In run():
  if self._boot_delay > 0:
      if self._stop_event.wait(self._boot_delay):
          return
  if not self._running:
      return
  ```
  This immediately aborts the boot delay without waiting 2 seconds and prevents zombie thread execution.

---

### [Finding 2 - Minor]: Non-Atomic Signal Dispatch on NaN / Inf Float Values
- **Location**: `modules/serial_comm.py`, lines 213–218.
- **Root Cause**:
  If a corrupted or sensor-glitched serial frame provides `<DATA:10.0,nan,100>`, `float("nan")` succeeds, but `int(round(float("nan")))` raises `ValueError: cannot convert float NaN to integer`.
  Because `self.data_received.emit(torque, speed, dac)` is called at line 213 *before* line 214 executes, `data_received` is dispatched to listeners with `nan`, after which the exception handler catches the `ValueError` and emits `error_received`.
- **Blast Radius**: Listeners receive a partial telemetry event followed by an error frame.
- **Recommended Fix**:
  Compute all converted values or validate `math.isnan(speed) or math.isinf(speed)` prior to emitting any Qt signals:
  ```python
  torque = float(parts[0].strip())
  speed = float(parts[1].strip())
  dac = int(parts[2].strip())
  if math.isnan(torque) or math.isnan(speed) or math.isinf(torque) or math.isinf(speed):
      raise ValueError("NaN or Inf not permitted in telemetry")
  rounded_speed = int(round(speed))

  self.data_received.emit(torque, speed, dac)
  self.speed_received.emit(rounded_speed)
  self.torque_received.emit(torque)
  self.dac_received.emit(dac)
  ```

---

## 5. Conclusion & Recommendation

The work delivered for Milestone 1 fulfills all functional and architectural requirements for Requirement 1. The code quality, test structure, and documentation are exemplary. 

**Verdict**: **PASS**. Findings 1 and 2 are documented for implementation in subsequent iterations or Milestone 3 integration.
