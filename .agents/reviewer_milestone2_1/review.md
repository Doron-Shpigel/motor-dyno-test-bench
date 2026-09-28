# Milestone 2 Requirement 3 Review & Adversarial Audit Report

**Date**: 2026-09-28  
**Reviewer**: Reviewer 1 (Archetype: reviewer / critic)  
**Target Requirement**: Milestone 2 Requirement 3 (R3) — Wire PID UI to Serial Commands  
**Artifacts Reviewed**:
- `gui/pid_tuning_tab.py`
- `gui/main_window.py`
- `tests/test_pid_tuning_tab.py`
- Supporting contracts: `arduino/dyno_controller/dyno_controller.ino`, `modules/serial_comm.py`
- Implementer Handoff: `.agents/worker_milestone2_1/handoff.md`

---

## 1. Review Summary

**Verdict**: **PASS** (APPROVE)  
**Overall Risk Assessment**: **LOW**  
**Integrity Audit**: **CLEAN (0 Violations)**

Worker 3's implementation satisfies all criteria for Requirement 3:
1. Signal signatures are decoupled and typed (`sig_read_pid`, `sig_set_pid(float, float, float)`, `sig_send_command(str)`, `sig_update_stability_params(float, float)`).
2. Input validation is non-blocking (in-place feedback label + `last_error` property; zero blocking modal dialogs).
3. 4-decimal precision formatting matches firmware parser expectations (`<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>`).
4. `MainWindow` wiring correctly coordinates worker lifecycle: auto-queries PID parameters on `DYNO_READY`, updates UI on `<PID_VALS:...>`, protects against offline transmissions, and decouples stability parameters.
5. All 19 unit & integration tests in `tests/test_pid_tuning_tab.py` pass cleanly in 0.308s, and the complete 102-test repository suite passes in 1.949s with zero errors and zero failures.

---

## 2. Integrity Violation Audit

Actively evaluated against adversarial deception patterns:
- **Hardcoded test results / expected outputs**: None found. Real float conversions, boundary logic, and command formatting strings are computed dynamically.
- **Dummy or facade implementations**: None found. Signals fire real slots; inputs undergo real validation against firmware constraints; `MainWindow` binds real worker methods.
- **Task bypasses or external shortcuts**: None found. Implemented with core PyQt6 primitives (`pyqtSignal`, `pyqtSlot`, `QLineEdit`, `QDoubleSpinBox`, `QTest`).
- **Fabricated verification logs**: None found. Independently executed unit and full test discovery runners synchronously in the execution environment.
- **Self-certifying work**: None found. Verified independently via code inspection, AST/py_compile validation, and test harness execution.

---

## 3. Requirement Verification & Findings

### Core Requirement Checklist

| Requirement Dimension | Target Specification | Observed Implementation | Status |
|---|---|---|---|
| **Signal Signatures** | Decoupled Qt signals for read, set, command, and stability | `sig_read_pid` (0 args), `sig_set_pid` (3 floats), `sig_send_command` (1 str), `sig_update_stability_params` (2 floats) | **PASS** |
| **Input Validation** | Non-blocking, rejects negative, non-numeric, NaN, Inf, empty, >1000 | `validate_inputs(allow_zero=True)` checks `math.isfinite`, `val < 0.0`, `val > 1000.0`, non-empty strings. Inline `_feedback_label` and `last_error` | **PASS** |
| **Command Formatting** | `<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>` | `cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"` | **PASS** |
| **EEPROM Query Command** | `<GET_PID>` | Emitted via `sig_send_command.emit("<GET_PID>")` | **PASS** |
| **MainWindow Routing** | Route commands to `SerialWorker`, handle disconnected state | `_on_pid_send_command` transmits when `_connected and _worker`, else warns in status bar | **PASS** |
| **Auto-Read on Ready** | Query gains when hardware is ready | `worker.ready.connect(self._on_arduino_ready)` -> `_worker.send_get_pid()` | **PASS** |
| **Telemetry Ingestion** | Populate stored values on `<PID_VALS:...>` | `worker.pid_received.connect(self._pid_tab.set_stored_values)` and `_on_pid_received` status reporting | **PASS** |
| **Stability Forwarding** | Forward params to monitor if present | Guarded with `hasattr(self, "_stability_monitor")` supporting `set_parameters` and `update_parameters` | **PASS** |

### Minor Observations & Recommendations (Non-Blocking)

#### [Minor] Finding 1: Stale File-Level Docstring
- **Location**: `gui/pid_tuning_tab.py:9-10`
- **What**: Docstring states: `"No backend logic is implemented here; all action slots are stubs."`
- **Why**: Action slots and input validation are now fully implemented.
- **Suggestion**: Update file header docstring to reflect completed functionality.

#### [Minor] Finding 2: Negative Zero Formatting
- **Location**: `gui/pid_tuning_tab.py:372`
- **What**: Entering `"-0.0"` passes validation because in Python `-0.0 < 0.0` evaluates to `False`. The resulting command is formatted as `<SET_PID:-0.0000,1.0000,1.0000>`.
- **Why**: While Arduino's `toFloat()` parses `"-0.0000"` to `-0.0` (which satisfies `!(pid.Kp < 0)` in C++), formatting with a negative sign on zero is cosmetically irregular.
- **Suggestion**: In `validate_inputs()`, add `if val == 0.0: val = 0.0` to normalize `-0.0` to `+0.0`.

#### [Minor] Finding 3: Potential Dual-Emission if Callback and Signal Both Used
- **Location**: `gui/pid_tuning_tab.py:406, 419`
- **What**: `_on_read_from_arduino` and `_on_save_to_arduino` emit `sig_send_command` AND invoke `self._command_sender(cmd)` if provided.
- **Why**: If an external consumer both provides `command_sender` and connects `sig_send_command`, duplicate commands would be dispatched to the serial port.
- **Note**: In `MainWindow`, `command_sender` is `None` and only `sig_send_command` is connected, so no duplicate commands occur in the application.

---

## 4. Adversarial Challenges & Stress-Testing

### Challenge 1: Boundary & Malformed Numeric Ingestion
- **Hypothesis**: Edge inputs like scientific notation (`1e2`, `1e-5`), European comma decimals (`1,5`), or `NaN`/`Inf` could bypass validation or break Arduino comma tokenization.
- **Stress-Test Results**:
  - `1e2` -> parses to `100.0000` (valid, accepted).
  - `1,5` -> rejected with `"Field KP must be a valid number."` (protects Arduino delimiter parser from splitting on comma).
  - `NaN`, `Inf`, `-Inf`, `"nan"` -> rejected by `not math.isfinite(val)`.
  - Empty string or whitespace -> rejected with `"Field KP cannot be empty."`.
  - Values `> 1000.0` (e.g. `1000.0001`) -> rejected with `"Field KP exceeds maximum limit of 1000.0"`.
- **Assessment**: PASS.

### Challenge 2: Ingestion of Corrupted Firmware Frames
- **Hypothesis**: Arduino firmware transmitting corrupt or NaN PID values could crash `set_stored_values`.
- **Stress-Test Results**:
  - `set_stored_values(float("nan"), 10.0, float("inf"))` -> renders `("ERR", "10.0000", "ERR")` without crashing.
  - Defense-in-depth: `modules/serial_comm.py` also validates `math.isfinite` before emitting `pid_received`.
- **Assessment**: PASS.

### Challenge 3: Worker Teardown & Reconnect Race Conditions
- **Hypothesis**: Disconnecting or stopping `SerialWorker` while asynchronous signals are pending could trigger `AttributeError` or `RuntimeError` in `MainWindow`.
- **Stress-Test Results**:
  - `_on_arduino_ready` guards worker access with `if self._worker:`.
  - `_start_worker` cleanly reconnects `ready` and `pid_received` to newly instantiated worker instances without signal leakage.
  - `_on_pid_send_command` cleanly checks `self._worker and self._connected`.
- **Assessment**: PASS.

---

## 5. Independent Test Verification Log

Commands executed:
1. `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_pid_tuning_tab.py -v`
   - Result: **19 tests passed** in 0.308s (0 failures, 0 errors).
2. `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v`
   - Result: **102 tests passed** in 1.949s (0 failures, 0 errors).
3. `.env/bin/python -m py_compile gui/pid_tuning_tab.py gui/main_window.py tests/test_pid_tuning_tab.py`
   - Result: Clean compilation (exit code 0).
