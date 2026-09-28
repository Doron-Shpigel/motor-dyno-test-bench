# Adversarial Stress Test & Vulnerability Report — Milestone 1 (Serial Protocol)

**Agent**: Challenger 1 (Critic / Specialist)  
**Date**: 2026-09-28  
**Scope**: `modules/serial_comm.py` (`SerialWorker`, line parser, thread lifecycle, outgoing commands)  
**Verification Suite**: `tests/test_serial_adversarial.py`  
**Overall Risk Assessment**: **HIGH (CRITICAL CONCURRENCY BUG CONFIRMED)**  
**Verdict**: **FAILED** (Implementation failed adversarial challenge due to thread teardown deadlocks and partial emission anomalies)

---

## 1. Executive Summary

An adversarial empirical evaluation of `modules/serial_comm.py` was conducted across four major challenge dimensions:
1. **High-Throughput Streaming & Queue Saturation**: Tested sustained bursts of 10,000 telemetry packets and 5,000 bidirectional concurrent commands.
2. **Frame Corruption, Noise, and Fragmentation**: Injected split frames across read boundaries, leading/trailing noise, Unicode surrogates, binary garbage, and massive payloads.
3. **Extreme Numerical Values & Type Coercion**: Injected `NaN`, `Inf`, scientific exponents (`1e-5`, `1e308`), integer overflow, and out-of-range DAC values.
4. **Thread Concurrency & Teardown Race Conditions**: Executed rapid start/stop/disconnect cycles under varied boot delay conditions.

### Key Finding
A **CRITICAL race condition deadlock** was discovered and empirically reproduced with a 100% failure rate in `SerialWorker`. When `worker.stop()` is called immediately after `start()` or during `boot_delay`, line 151 (`self._running = True`) unconditionally overwrites the stop request. The worker thread continues running indefinitely, causing `worker.wait()` to deadlock the calling (GUI) thread.

Additionally, a **partial emission bug** was discovered where invalid `speed` values (`NaN` or `Inf`) cause `data_received` to emit with corrupt values before `round(speed)` throws an unhandled exception that bypasses `torque_received` and `dac_received` while triggering `error_received`.

---

## 2. Challenge Findings & Vulnerability Matrix

| ID | Category | Severity | Description | Empirical Reproduction |
|---|---|---|---|---|
| **BUG-01** | Concurrency / Threading | **CRITICAL** | `stop()` during `boot_delay` or immediately post-`start()` is overwritten by `self._running = True` at line 151, causing worker thread to run forever and deadlock `worker.wait()`. | **100% failure rate** (50/50 runs deadlocked) |
| **BUG-02** | Concurrency / Responsiveness | **HIGH** | Uninterruptible `time.sleep(self._boot_delay)` forces caller to block for up to 2.0s during application shutdown or connection cancellation. | Verified by timing probe |
| **BUG-03** | Data Integrity / Parser | **MEDIUM** | Partial emission anomaly: In `<DATA:t,s,d>`, when `s` is `NaN` or `Inf`, `data_received.emit(t, s, d)` fires before `round(s)` raises an exception. `torque_received` and `dac_received` are skipped, leaving downstream consumers in an inconsistent state. | Confirmed via `test_nan_in_speed_partial_emission_anomaly` |
| **BUG-04** | Streaming / Robustness | **MEDIUM** | Split / fragmented lines across `readline()` timeouts are not reassembled. First chunk triggers missing closing bracket error; second chunk is silently discarded. | Confirmed via `test_split_and_fragmented_lines` |
| **BUG-05** | Numerical Bounds | **LOW** | `NaN` and `Inf` in torque are silently emitted downstream without validation or clamping. Large speeds (`1e308`) overflow PyQt's 32-bit C++ int in `speed_received`. DAC values are not range-checked (0–4095). | Confirmed via `test_nan_and_inf_in_torque` & `test_int_overflow_in_speed_received` |

---

## 3. Deep Dive: Challenges & Attack Scenarios

### Challenge 1 (CRITICAL): Thread Teardown Deadlock via Race Condition on `_running`
- **Location**: `modules/serial_comm.py` lines 84, 122–124, 143–144, 151
  ```python
  def __init__(...):
      self._running = False

  def stop(self) -> None:
      self._running = False

  def run(self) -> None:
      ...
      if self._boot_delay > 0:
          time.sleep(self._boot_delay)   # Line 144: Sleep cannot be aborted
      ...
      self._running = True               # Line 151: OVERWRITES stop()!
      self.connected.emit()
      while self._running:
          ...
  ```
- **Attack Scenario**:
  A user clicks "Connect" in the GUI, but immediately clicks "Cancel" or "Disconnect" (or closes the window). The GUI thread calls `worker.start()` followed immediately by `worker.stop()` and `worker.wait()`.
- **Observed Behavior**:
  1. Caller thread calls `worker.stop()`, setting `self._running = False`.
  2. Background thread wakes from `time.sleep(boot_delay)` or reaches line 151.
  3. Background thread unconditionally executes `self._running = True`.
  4. The background thread enters `while self._running:` and never terminates!
  5. The GUI thread blocks forever inside `worker.wait()`, freezing the application process.
- **Empirical Proof**:
  Running 50 consecutive `worker.start(); worker.stop(); worker.wait(1000)` calls resulted in **50 out of 50 hangs (100% failure)**.
- **Blast Radius**:
  Application-level freeze / hang requiring `kill -9` whenever a connection is quickly toggled or cancelled.
- **Recommended Mitigation**:
  1. Track a dedicated cancellation request flag: `self._stop_requested = False`.
  2. In `stop()`: `self._stop_requested = True; self._running = False`.
  3. In `run()`: Check `if self._stop_requested: return` before opening port, during `boot_delay`, and before line 151. Only set `self._running = True` if `not self._stop_requested`.
  4. Break `boot_delay` into short increments (e.g. loops of 50ms) checking `if self._stop_requested: break`.

---

### Challenge 2 (MEDIUM): Inconsistent Partial Signal Emission on `NaN` / `Inf`
- **Location**: `modules/serial_comm.py` lines 209–218
  ```python
  torque = float(parts[0].strip())
  speed = float(parts[1].strip())
  dac = int(parts[2].strip())

  self.data_received.emit(torque, speed, dac)       # Line 213: FIRES WITH NaN!
  self.speed_received.emit(int(round(speed)))       # Line 214: RAISES ValueError!
  self.torque_received.emit(torque)                 # Line 215: SKIPPED!
  self.dac_received.emit(dac)                       # Line 216: SKIPPED!
  ```
- **Attack Scenario**:
  Arduino emits `<DATA:12.5,NaN,2048>` (e.g. sensor floating-point division by zero).
- **Observed Behavior**:
  `float('NaN')` succeeds. `self.data_received.emit(12.5, nan, 2048)` executes and notifies subscribers.
  Next line `round(speed)` throws `ValueError: cannot convert float NaN to integer`.
  Control immediately transfers to `except Exception as exc:`, emitting `error_received`.
  Subscribers to `torque_received` and `dac_received` are never updated.
  Subscribers to `data_received` receive invalid `NaN` while simultaneously an error signal is broadcast.
- **Blast Radius**:
  Downstream subsystems (e.g. `StabilityMonitor` in Milestone 3) receive `NaN` values that invalidate rolling variance calculations and corrupt PID setpoint gating.
- **Recommended Mitigation**:
  Validate `math.isnan(val)` and `math.isinf(val)` on all floats before emitting any signals. If invalid, reject the entire frame cleanly.

---

### Challenge 3 (MEDIUM): Lack of Frame Reassembly on Chunked / Split Reads
- **Location**: `modules/serial_comm.py` lines 170–177
  ```python
  raw = self._serial.readline()
  if raw:
      self._parse_line(raw.decode(errors="replace").strip())
  ```
- **Attack Scenario**:
  Serial read timeout (`READ_TIMEOUT = 0.05s`) occurs mid-transmission of a 30-byte packet. `readline()` returns `b"<DATA:12.34,"`. The next read returns `b"1520.50,2048>\n"`.
- **Observed Behavior**:
  `_parse_line("<DATA:12.34,")` fails validation and emits `Malformed DATA frame ... (missing closing '>')`.
  The next read `"1520.50,2048>"` does not start with `<DATA:` and is discarded as unknown line noise.
  The entire packet is dropped.
- **Recommended Mitigation**:
  Maintain an internal byte buffer (`self._rx_buffer = bytearray()`). Only pass complete newline-terminated (`\n` or `\r\n`) lines to `_parse_line()`, retaining partial bytes across timeout intervals.

---

## 4. Stress Test Results & Benchmarks

| Test Case | Scenario / Parameters | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| `test_high_throughput_telemetry_burst` | 10,000 packets streamed continuously | >5,000 pkts/s, no leaks (<10MB growth) | **46,941 pkts/s**, 1.48MB heap diff | **PASS** |
| `test_bidirectional_saturation` | 5,000 incoming + 5,000 outgoing commands | Zero dropped commands, queue drain | 5,000 in / 5,001 out drained in 0.12s | **PASS** |
| `test_split_and_fragmented_lines` | Packet split into 2 chunks by read timeout | Frame recovery or clean error | Packet lost, error emitted | **PASS** (behavior documented) |
| `test_leading_noise_characters` | `\x00\xff<DATA:...>` UART startup noise | Safe drop or resync | Silently discarded without crash | **PASS** |
| `test_massive_payload_stress` | 100,000 characters payload | No crash / unhandled exception | Handled cleanly in 0.003s | **PASS** |
| `test_unicode_and_binary_garbage` | Emojis, surrogates, arbitrary binary bytes | No crash / graceful replace | Decoded with replacement chars, no crash | **PASS** |
| `test_nan_in_speed_partial_emission_anomaly` | `<DATA:15.5,NaN,2048>` | Atomic reject or clean handling | Partial emission bug reproduced | **PASS** (vulnerability confirmed) |
| `test_inf_in_speed_partial_emission_anomaly` | `<DATA:10.0,inf,1024>` | Atomic reject or clean handling | OverflowError caught, partial emission | **PASS** (vulnerability confirmed) |
| `test_nan_and_inf_in_torque` | `<DATA:NaN,1200.0,1000>` | Guarded float check | Emits `NaN` without error | **PASS** (vulnerability confirmed) |
| `test_scientific_exponents` | `<DATA:1.23e-4,5.67e+03,2000>` | Correct float conversion | 0.000123 N·m, 5670.0 RPM parsed | **PASS** |
| `test_int_overflow_in_speed_received` | `<DATA:10.0,1e308,2048>` | PyQt signal safety | Python int truncated to 32-bit int | **PASS** |
| `test_dac_out_of_bounds` | Negative and >4095 DAC values | DAC range validation | Emits raw int without clamping | **PASS** |
| `test_non_integer_dac` | Float DAC `<DATA:10,100,2048.5>` | Rejected as malformed | Malformed error emitted | **PASS** |
| `test_abrupt_disconnect_during_streaming` | Simulated USB cable unplug mid-stream | Graceful thread exit, error emitted | Clean shutdown, disconnected emitted | **PASS** |
| `test_immediate_stop_after_start_race_condition` | `start()` followed immediately by `stop()` | Thread terminates cleanly | **FAILED: 100% deadlock rate** | **FAIL** |
| `test_CRITICAL_early_stop_during_boot_delay_race_condition` | `stop()` called during `boot_delay` | Thread terminates cleanly | **FAILED: 100% deadlock rate** | **FAIL** |

---

## 5. Unchallenged Areas

- **Physical USB Baud Rate Clocks**: Real FTDI / CH340 hardware clock jitter and buffer overrun at physical 115200 baud under Linux kernel tty layer (requires physical dyno bench hardware).
- **Long-term 24-hour endurance**: Run continuous 24-hour stress tests to evaluate kernel serial buffer stability over extended durations (reserved for Milestone 4 E2E).

---

## 6. Verdict & Actionable Remediation Plan

### Verdict: **FAILED**
The implementation **failed** the adversarial challenge due to:
1. **Critical Concurrency Deadlock**: Inability of `SerialWorker` to handle rapid stop or teardown during startup, leading to application freezing.
2. **Partial Emission Anomaly**: Corrupt signal emission on `NaN` and `Inf` inputs.

### Remediation Requirements for Implementer:
1. **Fix Teardown Race Condition**:
   - Add `self._stop_requested = False` in `__init__`.
   - Set `self._stop_requested = True` in `stop()`.
   - In `run()`: Only set `self._running = True` if `not self._stop_requested`.
   - Make `boot_delay` cancellable: replace `time.sleep(self._boot_delay)` with a loop checking `self._stop_requested` every 20–50ms.
2. **Fix Partial Emission Bug**:
   - Validate numerical values with `math.isnan()` and `math.isinf()` before emitting any signals.
   - Clamp or validate DAC values to `0 <= dac <= 4095`.
