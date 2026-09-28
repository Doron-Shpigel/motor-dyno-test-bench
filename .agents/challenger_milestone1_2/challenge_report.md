# Adversarial Challenge Report: SerialWorker (`modules/serial_comm.py`)
**Author**: Challenger 2 (Milestone 1)  
**Date**: 2026-09-28  
**Target Module**: `modules/serial_comm.py`  
**Test Suite**: `tests/test_adversarial_boundary.py`  
**Execution Environment**: Python 3.11 (`.env/bin/python`)  

---

## 1. Challenge Summary

- **Overall Risk Assessment**: **HIGH / CRITICAL**
- **Verdict**: **FAILED** (Vulnerabilities and defect reproduction confirmed via automated tests)

We executed an adversarial test harness comprising 33 test cases targeting boundary conditions, corrupt/incomplete packet parsing, floating-point precision, and multi-threaded concurrency. The test suite revealed **1 critical thread lifecycle race condition**, **1 medium-severity partial emission defect on non-finite floats**, and **2 minor design/robustness observations**.

---

## 2. Identified Challenges & Failure Modes

### [CRITICAL] Challenge 1: Thread Termination Race During `boot_delay` (Unkillable Thread / Port Leak)

- **Assumption Challenged**:
  `SerialWorker.stop()` reliably halts worker execution at any point in its lifecycle.
- **Attack Scenario**:
  A caller starts `SerialWorker` and subsequently calls `stop()` while the worker thread is in its `boot_delay` sleep (default 2.0s):
  ```python
  worker = SerialWorker(port="/dev/ttyUSB0", boot_delay=2.0)
  worker.start()
  # User quickly closes window / cancels connection during boot delay
  worker.stop()
  worker.wait(1000) # Returns False! Thread is still running!
  ```
  In `modules/serial_comm.py`:
  1. `run()` enters `time.sleep(self._boot_delay)`.
  2. While sleeping, `stop()` sets `self._running = False`.
  3. `time.sleep()` finishes.
  4. Line 151 executes: `self._running = True`. **This unconditionally clobbers `self._running = False`!**
  5. The loop `while self._running:` begins and never exits until another `stop()` is explicitly called.
- **Blast Radius**:
  High/Critical. If a user connects to a port and quickly disconnects or closes the application, the background thread remains alive indefinitely in an infinite loop, retaining ownership of the serial port and preventing reconnection. In addition, GUI application exit can hang or crash due to lingering QThreads.
- **Empirical Proof**:
  Verified in `tests/test_adversarial_boundary.py::TestConcurrentWritesAndThreadSafety::test_stop_during_boot_delay_race_condition`.
  The test failed with `AssertionError: False is not true : VULNERABILITY CONFIRMED: Calling stop() during boot_delay was overwritten by self._running = True, thread failed to exit!`
- **Recommended Mitigation**:
  Implement an explicit `_stop_requested` boolean event or flag and check it before setting `self._running = True`. Make `boot_delay` interruptible:
  ```python
  def __init__(self, ...):
      ...
      self._stop_requested = False

  def stop(self) -> None:
      self._stop_requested = True
      self._running = False

  def run(self) -> None:
      ...
      if self._boot_delay > 0:
          deadline = time.time() + self._boot_delay
          while time.time() < deadline:
              if self._stop_requested:
                  return
              time.sleep(0.05)

      if self._stop_requested:
          return

      self._running = True
      self.connected.emit()
  ```

---

### [MEDIUM] Challenge 2: Partial Signal Emission on `NaN` / `Inf` Telemetry Data

- **Assumption Challenged**:
  `_parse_line` is atomic: either a valid packet produces complete telemetry signals (`data_received`, `speed_received`, `torque_received`, `dac_received`), or an invalid packet results in `error_received` without emitting corrupted partial signals.
- **Attack Scenario**:
  Arduino sends (or line noise produces) a frame with `nan` or `inf` in the speed field, e.g., `<DATA:15.0,nan,1024>`.
  In `_parse_line`:
  ```python
  torque = float(parts[0].strip()) # 15.0
  speed = float(parts[1].strip())   # nan (valid float in Python!)
  dac = int(parts[2].strip())       # 1024

  self.data_received.emit(torque, speed, dac) # EMITTED!
  self.speed_received.emit(int(round(speed))) # RAISES ValueError: cannot convert float NaN to integer
  self.torque_received.emit(torque)           # NEVER REACHED
  self.dac_received.emit(dac)                 # NEVER REACHED
  ```
  The `ValueError` is caught by `except Exception as exc:`, emitting `error_received`.
- **Blast Radius**:
  Downstream slots connected to `data_received` (such as real-time chart plotters or CSV loggers) receive `NaN` values and may crash, enter illegal states, or log corrupt rows. Meanwhile, convenience signals (`speed_received`, `torque_received`, `dac_received`) never fire, creating state divergence across GUI components.
- **Empirical Proof**:
  Verified in `tests/test_adversarial_boundary.py::TestIncompleteAndMalformedPackets::test_nan_speed_behavior_partial_emission`.
- **Recommended Mitigation**:
  Validate numeric sanity (`math.isnan()` / `math.isinf()` checks) or compute `int(round(speed))` *before* emitting any signals:
  ```python
  import math

  torque = float(parts[0].strip())
  speed = float(parts[1].strip())
  dac = int(parts[2].strip())
  if math.isnan(torque) or math.isnan(speed) or math.isinf(torque) or math.isinf(speed):
      raise ValueError("Telemetry contains NaN or Inf values")
  rounded_speed = int(round(speed))
  
  self.data_received.emit(torque, speed, dac)
  self.speed_received.emit(rounded_speed)
  self.torque_received.emit(torque)
  self.dac_received.emit(dac)
  ```

---

### [LOW-MEDIUM] Challenge 3: Silent Underflow / Truncation in Float Formatting

- **Assumption Challenged**:
  `send_set_pid` and `send_set_torque` accurately preserve user inputs.
- **Attack Scenario**:
  - `send_set_pid(1e-5, 0.00004, 1.0)`: Formatted as `<SET_PID:0.0000,0.0000,1.0000>`. Micro-integral or small derivative gains are silently truncated to `0.0000`, turning off the control term.
  - `send_set_pid(float('nan'), ...)`: Formatted as `<SET_PID:nan,...>`. The Arduino `String.toFloat()` parses `nan` as `0.0`.
  - `send_set_torque(0.004)`: Formats as `<SET_TORQUE:0.00>`.
- **Blast Radius**:
  Subtle control loop discrepancies where small gains configured by user/automation scripts are silently set to zero.
- **Recommended Mitigation**:
  Add validation in `send_set_pid` and `send_set_torque` to check for non-negative values and non-zero minimum resolution, or raise a `ValueError` if a non-zero gain is rounded to zero.

---

### [LOW] Challenge 4: Outer Whitespace Sensitivity in `_parse_line`

- **Assumption Challenged**:
  `_parse_line` can safely parse raw unstripped string inputs.
- **Attack Scenario**:
  Calling `_parse_line("  <DATA:1.0,2.0,100>  ")` does not trigger `<DATA:` handler because `line.startswith("<DATA:")` evaluates to False. It is silently dropped as noise.
- **Blast Radius**:
  Low in production because `run()` applies `.strip()` to `raw.decode()`, but fragile if `_parse_line` is used in custom packet processing or test harnesses.
- **Recommended Mitigation**:
  Add `line = line.strip()` at the very beginning of `_parse_line()`.

---

## 3. Stress Test Results Summary

Test Suite: `tests/test_adversarial_boundary.py` (33 total tests)

| Test Group | Test Name | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| **Thread Safety** | `test_stop_during_boot_delay_race_condition` | Worker terminates promptly when `stop()` called during `boot_delay` | `self._running` overwritten to `True`; thread kept running | **FAIL** (Vulnerability) |
| **Thread Safety** | `test_concurrent_writes_high_volume` (1000 msgs) | All 1000 messages delivered in order, no loss | All 1000 delivered cleanly via `queue.Queue` | **PASS** |
| **Thread Safety** | `test_concurrent_typed_helpers` (100 msgs) | Interleaved `send_set_torque` and `send_set_pid` | All 100 commands correctly formatted and written | **PASS** |
| **Data Parsing** | `test_incomplete_data_missing_closing_tag` (`<DATA:`) | Emits `error_received` with descriptive message | Emits `Malformed DATA frame: ... (missing closing '>')` | **PASS** |
| **Data Parsing** | `test_incomplete_data_too_few_fields` (`<DATA:1.0,2.0>`) | Emits `error_received` | Emits `Malformed DATA frame: ... (Expected 3 fields, got 2)` | **PASS** |
| **Data Parsing** | `test_incomplete_data_too_many_fields` (`<DATA:1,2,3,4>`) | Emits `error_received` | Emits `Malformed DATA frame: ... (Expected 3 fields, got 4)` | **PASS** |
| **Data Parsing** | `test_incomplete_pid_too_few_fields` (`<PID_VALS:1,2>`) | Emits `error_received` | Emits `Malformed PID_VALS frame: ... (Expected 3 fields, got 2)` | **PASS** |
| **Data Parsing** | `test_incomplete_pid_missing_closing_tag` (`<PID_VALS:`) | Emits `error_received` | Emits `Malformed PID_VALS frame: ... (missing closing '>')` | **PASS** |
| **Data Parsing** | `test_nan_speed_behavior_partial_emission` | Detects partial emission before exception | `data_received` fired with NaN, followed by `error_received` | **PASS** (Confirmed Defect) |
| **Formatting** | `test_send_set_pid_sub_decimal_precision_loss` | Confirms rounding/underflow behavior | Underflows to `0.0000` | **PASS** (Observed) |
| **Formatting** | `test_send_set_torque_sub_decimal_rounding` | Confirms 2-decimal rounding | Rounds `0.004 -> 0.00`, `0.005 -> 0.01` | **PASS** (Observed) |
| **Whitespace** | `test_internal_extra_spaces_in_data_frame` | Trims internal whitespace properly | Correctly parsed | **PASS** |
| **Whitespace** | `test_thread_crlf_and_lf_handling_from_serial` | Handles `\r\n` and `\n` without error | Correctly parsed and emitted | **PASS** |

---

## 4. Unchallenged Areas

- **Serial Baud Rate Mismatch**: Baud rate mismatches at hardware driver level were not tested as hardware was mocked.
- **Physical Electrical Disconnect Glitches**: USB dropouts causing OS-level kernel buffer corruptions were simulated via `SerialException` but not real USB hardware bus resets.

---

## 5. Verdict and Next Steps

**Verdict**: **FAILED**

The implementation in `modules/serial_comm.py` fails the thread termination test during `boot_delay` and has an atomicity issue on malformed/non-finite float data. These issues should be resolved before Milestone 1 sign-off.
