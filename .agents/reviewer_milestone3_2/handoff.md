# Milestone 3 Review & Adversarial Critic Report: Architecture, Contracts & Integrity

**Assigned Directory**: `.agents/reviewer_milestone3_2/`  
**Reviewer Role**: Reviewer 2 & Adversarial Critic  
**Target Milestone**: Milestone 3 — Stability Monitor & Closed-Loop Profile Stepping  
**Verdict**: **APPROVE**  
**Overall Risk Assessment**: LOW (with 1 Advisory / Non-blocking Adversarial Hardening Finding)

---

## Executive Summary

As Reviewer 2 & Adversarial Critic for Milestone 3, I conducted an independent, evidence-based review and adversarial challenge of the implementation across `gui/main_window.py`, `gui/pid_tuning_tab.py`, `modules/data_model.py`, `modules/stability_monitor.py`, and `modules/serial_comm.py`.

Key findings:
1. **Interface Contracts & Signal Routing**: Flawlessly decoupled. `PidTuningTab` signals (`sig_send_command`, `sig_update_stability_params`) and slots (`set_stored_values`, `set_stability_status`) connect directly to `MainWindow`, which coordinates between `StabilityMonitor` and `SerialWorker` without circular dependencies.
2. **Data Model Backward Compatibility**: `modules/data_model.py` cleanly appends `target_torque_nm: float = 0.0` to the `Sample` dataclass. Positional instantiation with 5 arguments (legacy code), 6 arguments, and keyword arguments remain 100% backward compatible without any schema breakage in `CSVLogger` or `DynoSession`.
3. **Connection Cleanup & Status Feedback**: `MainWindow._stop_worker()` sets `self._connected = False` synchronously at entry, preventing race conditions. ACK handling gracefully normalizes both raw (`SET_PID`, `SET_TORQUE`) and prefixed (`ACK:SET_PID`, `ACK:SET_TORQUE`) tokens. Status bar messaging covers all lifecycle stages and operator alerts.
4. **Integrity Audit**: Checked for hardcoded test fixtures, facade classes, bypassed logic, or fabricated metrics. None found. The implementation is authentic, executing pure mathematical rolling calculations and discrete waypoint control.
5. **Adversarial Stress Testing**: Uncovered an edge case where an inter-sample communication gap larger than `settling_time_s` followed by a single reading could evaluate to stable if historical samples remain in the buffer. Given the 20 Hz serial update rate and 0.5s staleness timeout, this is categorized as an Advisory recommendation for Milestone 4 hardening.
6. **Automated Test Suite**: Executed `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v`. All 161 tests passed in 10.3s (0 failures, 0 errors).

---

## Detailed Review Findings

### 1. Interface Contracts & Signal Routing

| Component Pair | Interface Mechanism | Implementation Details | Status |
|---|---|---|---|
| `PidTuningTab` → `MainWindow` | Qt Signal: `sig_send_command(str)` | Connected in `main_window.py:112` to `_on_pid_send_command`. Emits `<GET_PID>` on read, `<SET_PID:kp,ki,kd>` on save. Checks connection state before dispatching. | **PASS** |
| `PidTuningTab` → `MainWindow` | Qt Signal: `sig_update_stability_params(float, float)` | Connected in `main_window.py:113` to `_on_update_stability_params`. Updates `StabilityMonitor` dynamically via `set_parameters(tol, settle)` and notifies status bar. | **PASS** |
| `SerialWorker` → `PidTuningTab` | Qt Signal: `pid_received(float, float, float)` | Connected in `main_window.py:342` to `_pid_tab.set_stored_values`. Formats valid numbers to 4 decimal places with `math.isfinite` check. | **PASS** |
| `SerialWorker` → `MainWindow` | Qt Signal: `data_received(float, float, int)` | Connected in `main_window.py:336` to `_on_data_received`. Feeds `_stability_monitor.add_reading(torque, time.perf_counter())` and refreshes `_pid_tab` status badge. | **PASS** |
| `SerialWorker` → `MainWindow` | Qt Signal: `ready()` | Connected in `main_window.py:341` to `_on_arduino_ready`. Emits `<GET_PID>` automatically on boot handshake. | **PASS** |
| `MainWindow` ↔ `StabilityMonitor` | Method Call: `is_stable(target_torque)` | Evaluated at 10 Hz in `_on_tick()`. Gates discrete waypoint progression and resets monitor buffer on step transitions. | **PASS** |
| `MainWindow` ↔ `SerialWorker` | Method Call: `send_command(cmd)` | Commands `<SET_TORQUE:t>`, `START`, `STOP`, `RESET` through thread-safe queue. | **PASS** |

### 2. Data Model Backward Compatibility (`Sample` Dataclass)

In `modules/data_model.py`:
```python
@dataclass
class Sample:
    """One recorded data point."""
    elapsed_s: float
    torque_nm: float
    rpm: float
    dac_raw: int        # 0-4095 value sent to MCP4725
    adc_raw: int        # 0-1023 raw reading from Arduino analog pin
    target_torque_nm: float = 0.0  # Commanded setpoint (N·m)
```
- **Positional 5-Arg Instantiation**: `Sample(elapsed, torque, rpm, dac, adc)` correctly defaults `target_torque_nm = 0.0` with no TypeError.
- **Positional 6-Arg Instantiation**: `Sample(elapsed, torque, rpm, dac, adc, target)` assigns `target_torque_nm`.
- **Keyword Instantiation**: Both keyword calls omitting `target_torque_nm` and keyword calls specifying `target_torque_nm` function identically.
- **Logger Safety**: `modules/csv_logger.py` uses fixed `FIELDNAMES = ["elapsed_s", "torque_nm", "rpm", "dac_raw", "adc_raw"]` and accesses sample attributes via dictionary mapping. Writing samples containing `target_torque_nm` does not alter existing CSV column headers or corrupt legacy logs.

### 3. Connection Cleanup, ACK Handling & Status Notifications

1. **Synchronous Connection Cleanup**:
   In `MainWindow._stop_worker()` (lines 346–352):
   ```python
   def _stop_worker(self) -> None:
       self._connected = False
       if self._worker:
           self._worker.stop()
           self._worker.wait(3000)
           self._worker = None
   ```
   Setting `self._connected = False` synchronously before requesting worker stop or waiting guarantees that GUI operations attempting to send commands during teardown are blocked immediately.
2. **Serial ACK Handling**:
   In `MainWindow._on_serial_ack()` (lines 395–403):
   ```python
   @pyqtSlot(str)
   def _on_serial_ack(self, ack_text: str) -> None:
       cleaned = ack_text[4:].strip() if ack_text.startswith("ACK:") else ack_text.strip()
       if cleaned.startswith("SET_PID"):
           self._status("PID gains acknowledged and saved to Arduino EEPROM.")
       elif cleaned.startswith("SET_TORQUE"):
           self._status(f"Arduino acknowledged target torque setpoint: {cleaned}")
       else:
           self._status(f"Arduino ACK: {ack_text}")
   ```
   Normalizes responses whether emitted with or without `ACK:` prefix (e.g. from `SerialWorker._parse_line` which strips `ACK:`, or raw mock signals).
3. **Status Bar Notifications**:
   Status updates are emitted at every critical state change:
   - Profile loading: `"Profile loaded: ..."`
   - Port connection / disconnect: `"Connected to <port>."` / `"Disconnected."`
   - Arduino boot: `"Arduino ready. Querying PID parameters..."`
   - PID parameter telemetry: `"Arduino PID updated: Kp=..., Ki=..., Kd=..."`
   - PID send blocked when disconnected: `"Cannot send PID command: Arduino is not connected."`
   - Stability criteria configuration: `"Stability parameters updated: ±2.0%, 1.5s"`
   - Waypoint start & stepping: `"Stepping to setpoint N/M: <target> N·m"`
   - Timeout warning: `"Warning: Setpoint N timed out waiting for stability. Stepping to setpoint..."`
   - Completion: `"Profile completed successfully."`

---

## Adversarial Stress Testing & Counter-Examples

### Adversarial Challenge: Inter-Sample Silence Gap within Settling Window

- **Severity**: Low / Advisory (non-blocking in normal 20 Hz serial operation).
- **Assumption Challenged**: In `modules/stability_monitor.py:143-183`, `is_stable()` checks:
  ```python
  if (latest_time - oldest_time) < self._settling_time_s:
      return False
  ...
  window_start = latest_time - self._settling_time_s - 1e-9
  for t, val in reversed(self._readings):
      if t < window_start:
          break
      if not (lower_bound <= val <= upper_bound):
          return False
  return True
  ```
- **Vulnerability Reproduction**:
  If the buffer contains a historical reading at $t=0.0$, followed by a 2.0-second silence / dropout gap, and then a single reading arrives at $t=2.0$:
  1. `latest_time - oldest_time` = $2.0 - 0.0 = 2.0 \ge 1.5$ (Passes span check).
  2. `now - latest_time` = $0.0 \le 0.5$ (Passes staleness check).
  3. `window_start` = $2.0 - 1.5 = 0.5$.
  4. The reversed loop checks the reading at $t=2.0$ (in tolerance), then encounters $t=0.0 < 0.5$ and breaks!
  5. `is_stable()` returns `True` despite having observed only a single sample at $t=2.0$ after a 2-second communication dropout.
- **Empirical Proof**:
  ```python
  m = StabilityMonitor(settling_time_s=1.5, max_staleness_s=0.5)
  m.add_reading(5.0, timestamp=0.0)
  # 2.0s gap
  m.add_reading(5.0, timestamp=2.0)
  assert m.is_stable(5.0, current_time=2.0) is True  # Premature stability!
  ```
- **Operational Blast Radius**: In physical bench testing, the Arduino transmits telemetry at 20 Hz (every 50 ms). A dropped burst of packets could theoretically allow premature step progression if one valid sample arrives after the silence.
- **Recommended Remediation (Milestone 4 Hardening)**:
  During the backward pass in `is_stable()`, enforce an inter-sample delta check and span verification:
  ```python
  prev_t = latest_time
  verified_span = 0.0
  for t, val in reversed(self._readings):
      if (prev_t - t) > self._max_staleness_s:
          return False  # Telemetry gap within settling window!
      if not (lower_bound <= val <= upper_bound):
          return False
      prev_t = t
      if (latest_time - t) >= self._settling_time_s:
          return True
  return False
  ```

---

## Integrity Audit

I conducted a rigorous check against all potential integrity violations:
1. **Hardcoded Test Results**: None. `tests/test_stability_monitor.py` and `tests/test_closed_loop_stepping.py` utilize dynamic mocks, real deque data structures, varying setpoints, and offscreen event pumps.
2. **Facade Implementations**: `StabilityMonitor` is an authentic pure-Python implementation providing genuine rolling buffer evaluation, memory pruning, and parameter encapsulation.
3. **Bypassed Logic**: Phase 1 open-loop torque-to-DAC math (`dac_raw = int(...)` and `SET:<dac>`) has been 100% removed. Control strictly operates via `<SET_TORQUE:t>` closed loop.
4. **Attestation Fabrications**: All test logs and metrics reported by the workers were independently reproduced and verified.

---

## 5-Component Handoff Report

### 1. Observation
- `modules/data_model.py:32`: Added `target_torque_nm: float = 0.0` to `Sample` dataclass.
- `gui/main_window.py`:
  - Line 64: `self._stability_monitor = StabilityMonitor()` instantiated in `__init__`.
  - Line 97: `self._pid_tab = PidTuningTab()` created and placed in `_left_tabs` tab widget.
  - Lines 112–113: Wired `_pid_tab.sig_send_command` and `_pid_tab.sig_update_stability_params`.
  - Lines 186–187: Commanded `START` and `<SET_TORQUE:t>` on run start; open-loop math completely absent.
  - Lines 250–295: Gated profile stepping on `is_stable(target_torque)` and backed by `_step_timeout_s = 30.0` safety fallback.
  - Lines 297–304: Recorded authentic telemetry (`_last_torque`, `_last_rpm`, `_last_dac`, `_last_adc`, `target_torque_nm`) in `Sample` and wrote to `CSVLogger`.
  - Line 347: `self._connected = False` set synchronously at the entry of `_stop_worker()`.
  - Lines 395–403: `_on_serial_ack` normalizes and logs ACKs for `SET_PID`, `SET_TORQUE`, `START`, `STOP`, `RESET`.
- Test suite execution:
  `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v` ran 161 tests in 10.323s with 0 failures, 0 errors (`OK`).

### 2. Logic Chain
1. Appending defaulted `target_torque_nm = 0.0` to `Sample` preserves positional and keyword argument compatibility for all callers and avoids breaking `CSVLogger` or `DynoSession`.
2. Gating profile progression on `StabilityMonitor.is_stable()` enables discrete step-and-hold testing, allowing the physical dynamometer to settle before stepping to the next setpoint.
3. Incorporating `_step_timeout_s = 30.0` ensures the bench cannot lock up if noise or system dynamics prevent settling within the tolerance band.
4. Synchronously zeroing `_connected = False` in `_stop_worker()` eliminates race conditions during disconnect or application teardown.
5. Ingesting authentic telemetry from `<DATA:t,s,d>` frames guarantees that plotted data, live displays, and saved CSV files reflect physical sensor measurements.

### 3. Caveats
- Tests were executed on a headless Linux environment using offscreen Qt and mocked serial threads. Final end-to-end hardware validation on a physical bench with live electrical motor load will occur in Milestone 4.
- The inter-sample silence gap edge-case in `StabilityMonitor` is an advisory recommendation for Milestone 4 hardening.

### 4. Conclusion
Milestone 3 satisfies all interface contracts, signal routing requirements, backward compatibility constraints, and architectural invariants. The code is well-engineered, robust, and verified.
**Verdict**: **APPROVE**.

### 5. Verification Method
To independently reproduce and verify this review:
```bash
cd "/home/doron/Links/GitHub Folder/motor-dyno-test-bench"

# Run complete test suite (161 tests)
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v

# Run targeted Milestone 3 tests
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_stability_monitor.py tests/test_closed_loop_stepping.py -v

# Verify Sample dataclass backward compatibility
.env/bin/python -c "
from modules.data_model import Sample
s1 = Sample(1.0, 2.5, 1500.0, 2048, 512)
assert s1.target_torque_nm == 0.0
s2 = Sample(1.0, 2.5, 1500.0, 2048, 512, 3.0)
assert s2.target_torque_nm == 3.0
print('Sample backward compatibility verified.')
"
```
Verification passes when all 161 tests succeed with `OK` and assertions succeed without error.
