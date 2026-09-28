# Changes Implemented — Milestone 1 Remediation (Worker 2)

## Target File: `modules/serial_comm.py`

### 1. Concurrency Defect & Thread Lifecycle Fixes in `SerialWorker`
- **Stop Flag Addition**: Added `self._stop_requested = False` in `SerialWorker.__init__`.
- **Atomic Stop Request**: Updated `SerialWorker.stop()` to set `self._stop_requested = True` and `self._running = False`.
- **Interruptible Boot Delay**: Replaced blocking `time.sleep(self._boot_delay)` in `SerialWorker.run()` with a 50ms polling loop that monitors `self._stop_requested` and `self._running`, terminating immediately if a stop request occurs:
  ```python
  if self._boot_delay > 0:
      end_time = time.monotonic() + self._boot_delay
      while time.monotonic() < end_time:
          if self._stop_requested or not self._running:
              return
          time.sleep(0.05)
  ```
- **Loop Entry Guard**: Verified `self._stop_requested or not self._running` prior to buffer clearing, loop entry, and connection signal emission.
- **Connection Emission Guard**: Enclosed in `if not self._stop_requested: self._running = True; self.connected.emit()`.
- **Comprehensive Cleanup**: Wrapped boot delay, initialization, and loop in `try ... finally:` ensuring `self._running = False`, DAC zeroing (`RESET\n`), port closure, and `disconnected.emit()` always occur on early termination.

### 2. Validation & Atomic Signal Emission in `SerialWorker._parse_line`
- **Whitespace Sanitization**: Added `line = line.strip()` at the very beginning of `_parse_line()` to prevent leading/trailing whitespace from causing frame drops or parsing errors.
- **Finite Float Checks for Telemetry Packet (`<DATA:t,s,d>`)**:
  - Imported `math`.
  - Added finite check: `if not (math.isfinite(torque) and math.isfinite(speed)): raise ValueError("Non-finite numeric values in DATA frame")`.
  - Computed `speed_int = int(round(speed))` before emitting any signals.
  - Ensured all signals (`data_received`, `speed_received`, `torque_received`, `dac_received`) are emitted strictly AFTER all validations and computations succeed. If any field is non-finite or corrupt, no partial signals are emitted and `error_received` is emitted with the exception.
- **Finite Float Checks for PID Packet (`<PID_VALS:p,i,d>`)**:
  - Added finite check: `if not (math.isfinite(kp) and math.isfinite(ki) and math.isfinite(kd)): raise ValueError("Non-finite values in PID frame")`.
  - Signals are emitted strictly after verification.

---

## Test Suites Updated: `tests/test_serial_adversarial.py` and `tests/test_adversarial_boundary.py`
- Updated test assertions in adversarial suites to verify that `NaN` and `Inf` in `speed` and `torque` are rejected atomically without partial emission (`len(data_records) == 0`, `len(speed_records) == 0`, `len(errors) == 1`).
- Added verification of non-finite PID packet rejection (`<PID_VALS:nan,...>`).
- Verified whitespace handling when calling `_parse_line` with outer padding.
