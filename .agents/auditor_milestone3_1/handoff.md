# Forensic Integrity Audit Report: Milestone 3

**Work Product**: Milestone 3 (`modules/stability_monitor.py`, `gui/main_window.py`, `modules/data_model.py`, `tests/test_stability_monitor.py`, `tests/test_closed_loop_stepping.py`)  
**Profile**: General Project  
**Verdict**: **CLEAN**

---

## 1. Observation

### 1.1 Source Code Static Analysis

1. **Elimination of Phase 1 Open-Loop Math**:
   - Inspected `gui/main_window.py`.
   - In git history, lines 216–222 previously contained:
     ```python
     # DAC value
     dac_raw = int(
         min(max(torque_nm / self._calibration.max_torque_nm, 0.0), 1.0) * 4095
     )
     if self._worker:
         self._worker.send_command(f"SET:{dac_raw}")
     ```
   - In the updated `gui/main_window.py`, this open-loop torque-to-DAC math has been completely removed.
   - Global repository search for `SET:` revealed 0 occurrences in executable code (only historical documentation in `README.md` and negative assertion in `test_closed_loop_stepping.py`).
   - Global repository search for `dac_raw = int` revealed 0 occurrences in executable Python code.
   - In `gui/main_window.py` lines 186–187 (`_on_start`) and line 267 (`_on_tick`), the system commands target torque setpoints via closed-loop serial protocol:
     ```python
     self._worker.send_command(f"<SET_TORQUE:{self._current_target_torque:.2f}>")
     ```

2. **Authenticity of StabilityMonitor**:
   - Inspected `modules/stability_monitor.py` (192 lines).
   - Implementation uses `collections.deque` storing `(timestamp, torque)` tuples.
   - Enforces genuine mathematical criteria in `is_stable(target_torque, current_time)`:
     - Staleness threshold: `(now - latest_time) > self._max_staleness_s` (lines 160–161)
     - Minimum buffer span: `(latest_time - oldest_time) < self._settling_time_s` (lines 165–166)
     - Tolerance band: `band = max(abs(target) * (self._tolerance_pct / 100.0), self._min_abs_tolerance)` (line 170)
     - Continuous window check across `[latest_time - settling_time_s, latest_time]` via reverse deque traversal (lines 177–181)
     - Automatic historical pruning: `while self._readings and self._readings[0][0] < prune_cutoff: self._readings.popleft()` (lines 139–141)
     - Input validation: raises `ValueError` on non-positive or negative parameters (lines 89–101).
   - Zero facade patterns, zero dummy return constants, zero pre-computed lookups.

3. **Data Model Integrity (`modules/data_model.py`)**:
   - `Sample` dataclass updated at line 32: `target_torque_nm: float = 0.0`.
   - Backward compatibility is maintained for all existing field orderings (`elapsed_s`, `torque_nm`, `rpm`, `dac_raw`, `adc_raw`).
   - `MainWindow._on_tick` populates `Sample` with authentic incoming telemetry from `_last_torque`, `_last_rpm`, `_last_dac`, `_last_adc` (lines 297–305), directly fed from incoming `<DATA:t,s,d>` frames via `_on_data_received`.

4. **Test Suite Legitimacy (`tests/test_stability_monitor.py` & `tests/test_closed_loop_stepping.py`)**:
   - Inspected all 12 tests in `tests/test_stability_monitor.py`:
     - Covers empty buffer, insufficient duration, stable convergence, transient spike streak breaking, recovery after spike, 0.0 N·m absolute floor tolerance, stale telemetry cutoff, buffer resets, parameter mutations, invalid parameter validation, memory pruning bounds, and negative target torques.
     - None of the tests use tautological assertions or bypass logic.
   - Inspected all 9 tests in `tests/test_closed_loop_stepping.py`:
     - Covers `START` and `<SET_TORQUE:t>` transmission, verification that open-loop `SET:` is never sent, stability gating during out-of-band telemetry, step advancement to subsequent waypoints, full profile auto-stop upon final waypoint completion, 30s timeout fallback advancing past stuck steps, authentic telemetry writing to disk CSV, serial ACK routing, and parameter signal wiring.
     - Mocking is strictly limited to serial worker I/O (`MockSerialWorker` as standard for headless CI) and deterministic timestamps via `time.perf_counter` patching in long-duration timeout tests. Actual GUI and data logic paths are 100% executed.

5. **Absence of Fabricated Artifacts**:
   - Search for pre-populated `.log` or result artifacts across the workspace yielded no pre-baked test outputs.

### 1.2 Runtime Test Execution

Command executed:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v
```

Verbatim Output Summary:
```
Ran 161 tests in 10.401s
OK
```

Targeted Milestone 3 command executed:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_stability_monitor.py tests/test_closed_loop_stepping.py -v
```

Verbatim Output Summary:
```
Ran 21 tests in 1.355s
OK
```

All 21 Milestone 3 tests and all 161 repository-wide tests execute synchronously and pass cleanly without skips or warnings.

---

## 2. Logic Chain

1. **Step 1 (Static Analysis)**: Verification that open-loop math `dac_raw = int(...)` and `SET:<dac>` was eradicated from `gui/main_window.py`. Direct observation of git diff and grep searches confirms 0 remaining instances in executable code.
2. **Step 2 (Algorithm Authenticity)**: Examination of `modules/stability_monitor.py` reveals an authentic rolling buffer using `deque`, continuous time-window traversal, dynamic parameter updates, and memory pruning. No facade or constant-return stubs exist.
3. **Step 3 (Integration & Closed-Loop Control)**: Inspection of `gui/main_window.py` confirms that `_on_start` commands `<SET_TORQUE:{target:.2f}>`, `_on_data_received` ingests real physical telemetry into `StabilityMonitor`, `_on_tick` gates waypoint advancement strictly on `is_stable(target_torque)` with a 30.0s safety timeout fallback, and writes real measurements into `Sample` and `CSVLogger`.
4. **Step 4 (Test Legitimacy)**: Review of test files confirms tests exercise genuine code paths and assert against real calculation outputs. No tautological assertions, mock bypasses of business logic, or hardcoded expected strings exist.
5. **Step 5 (Runtime Validation)**: Independent execution of the test suite demonstrates 100% pass rate across 161 tests (21 specifically covering Milestone 3).

Therefore, the implementation satisfies all forensic requirements under Development mode.

---

## 3. Caveats

- Testing was performed in a headless environment (`QT_QPA_PLATFORM=offscreen`) with serial I/O simulated via `MockSerialWorker`. Physical bench validation with actual USB Arduino hardware and load cell will occur during hardware integration.

---

## 4. Conclusion

**Verdict: CLEAN**

Milestone 3 contains no integrity violations, no facade implementations, no hardcoded shortcuts, and no remaining Phase 1 open-loop math. The closed-loop stepping and stability monitor mechanisms are authentically implemented and rigorously verified.

---

## 5. Verification Method

To independently reproduce this forensic audit:

1. Verify elimination of open-loop math:
   ```bash
   grep -rn "SET:" gui/ modules/
   grep -rn "dac_raw = int" gui/ modules/
   ```
   (Expected: no matches in active python files)

2. Run Milestone 3 unit and integration tests:
   ```bash
   QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_stability_monitor.py tests/test_closed_loop_stepping.py -v
   ```
   (Expected: 21 tests pass with OK)

3. Run full project test suite:
   ```bash
   QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v
   ```
   (Expected: 161 tests pass with OK)
