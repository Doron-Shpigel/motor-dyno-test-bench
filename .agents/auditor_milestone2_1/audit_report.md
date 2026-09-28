# Forensic Audit Report — Milestone 2

**Work Product**: Milestone 2 changes (`gui/pid_tuning_tab.py`, `gui/main_window.py`, `tests/test_pid_tuning_tab.py`)  
**Auditor**: Forensic Auditor (`auditor_milestone2_1`)  
**Profile**: General Project  
**Integrity Mode**: Development  
**Target Milestone**: Milestone 2 (PID UI Wiring & Telemetry Integration)  
**Date/Time**: 2026-09-28T13:58:30Z  
**Verdict**: **CLEAN**

---

## Executive Summary

An independent forensic integrity audit was performed on the Milestone 2 deliverables:
1. `gui/pid_tuning_tab.py`
2. `gui/main_window.py`
3. `tests/test_pid_tuning_tab.py`

All four forensic checks mandated for Milestone 2 were executed empirically in a clean Linux headless Qt environment (`QT_QPA_PLATFORM=offscreen`). Zero integrity violations were detected. No facade implementations, hardcoded outputs, mock flags, or pre-recorded test results were found. All 19 unit and integration tests in `tests/test_pid_tuning_tab.py` execute genuine logic and pass. Dynamic randomized testing confirmed authentic parsing, validation, and `<SET_PID:p,i,d>` command formatting across arbitrary floating-point values and boundary conditions.

---

## Phase Results

| Check # | Check Name | Status | Summary |
|---|---|:---:|---|
| **Check 1** | **Static Analysis & Logic Authenticity** | **PASS** | `validate_inputs()` implements genuine parsing, range checks (`0.0 <= val <= 1000.0`), finite checks (`math.isfinite`), and string formatting (`<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>`). No mock bypasses or hardcoded constants. |
| **Check 2** | **Acceptance Criteria Verification** | **PASS** | Confirmed that `pid_tuning_tab.py` correctly formats and transmits `<SET_PID:p,i,d>` with 4-decimal precision, and `main_window.py` routes the command to the worker when connected. |
| **Check 3** | **Runtime Tracing & Execution** | **PASS** | 19/19 tests in `test_pid_tuning_tab.py` passed in 0.424s. Python runtime tracing (`sys.settrace`) confirmed that 100% of tab methods and main window PID slots were actively executed during the test run. |
| **Check 4** | **Prohibited Patterns Check** | **PASS** | No hardcoded outputs, no facades, no pre-populated log/result files, no circular self-certifying tests, and zero mock flags in production code. |

---

## Detailed Forensic Evidence

### 1. Static Analysis & Input Validation

Inspection of `gui/pid_tuning_tab.py` confirmed authentic logic across all inputs:
- Text is read dynamically from `QLineEdit` input fields (`self._inputs["kp"]`, `self._inputs["ki"]`, `self._inputs["kd"]`).
- Non-empty and whitespace checks: `text = line_edit.text().strip(); if not text: return None`.
- Numeric conversion with exception handling: `float(text)`.
- Defense against non-finite values: `math.isfinite(val)` rejects `NaN`, `Inf`, `-Inf`, and `Infinity`.
- Firmware boundary enforcement: `val < 0.0` and `val > 1000.0` (matching Arduino firmware limits in `dyno_controller.ino:67`).
- Zero-gain allowance parameter: `allow_zero=True` allows `0.0` (essential for PI / PD loops) while permitting strict positivity when configured.
- Command string formatting: `cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"` strictly produces the 4-decimal format expected by the Arduino C++ token parser.
- Decoupled Qt signals: `sig_read_pid = pyqtSignal()`, `sig_set_pid = pyqtSignal(float, float, float)`, `sig_send_command = pyqtSignal(str)`, `sig_update_stability_params = pyqtSignal(float, float)`.
- Non-blocking user feedback: Displays error messages in `self._feedback_label` and exposes `self.last_error` property without popping blocking modal dialogs that would freeze background threads.

### 2. MainWindow Integration & Signal Routing

Inspection of `gui/main_window.py` verified:
- `self._pid_tab = PidTuningTab()` is instantiated and embedded in the left-hand tab widget `_left_tabs`.
- Signal connections established in `_build_ui()`:
  - `self._pid_tab.sig_send_command.connect(self._on_pid_send_command)`
  - `self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)`
- Worker connections established in `_start_worker()`:
  - `self._worker.ready.connect(self._on_arduino_ready)` -> automatically triggers `self._worker.send_get_pid()`
  - `self._worker.pid_received.connect(self._pid_tab.set_stored_values)` -> populates stored values directly upon receiving `<PID_VALS:...>`
  - `self._worker.pid_received.connect(self._on_pid_received)` -> logs status update
- Safe connection state checking:
  - `_on_pid_send_command` explicitly checks `if self._worker and self._connected:` before attempting to transmit. When disconnected, it prevents transmission and warns via the status bar.

### 3. Empirical Test Execution & Runtime Tracing

#### A. Automated Unit & Integration Suite
Command executed:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_pid_tuning_tab.py -v
```
Output:
```text
test_arduino_ready_triggers_auto_query (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_arduino_ready_triggers_auto_query) ... ok
test_direct_pid_helper_slots (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_direct_pid_helper_slots) ... ok
test_read_pid_routing_when_connected (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_read_pid_routing_when_connected) ... ok
test_read_pid_routing_when_disconnected (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_read_pid_routing_when_disconnected) ... ok
test_save_pid_routing_when_connected (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_save_pid_routing_when_connected) ... ok
test_save_pid_routing_when_disconnected (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_save_pid_routing_when_disconnected) ... ok
test_software_stability_update_routing (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_software_stability_update_routing) ... ok
test_start_worker_wires_pid_and_ready_signals (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_start_worker_wires_pid_and_ready_signals) ... ok
test_telemetry_updates_pid_tab (tests.test_pid_tuning_tab.TestMainWindowPidIntegration.test_telemetry_updates_pid_tab) ... ok
test_default_state (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_default_state) ... ok
test_read_button_emits_signals (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_read_button_emits_signals) ... ok
test_read_button_with_command_sender (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_read_button_with_command_sender) ... ok
test_save_boundary_values (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_save_boundary_values) ... ok
test_save_invalid_inputs_comprehensive (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_save_invalid_inputs_comprehensive) ... ok
test_save_valid_inputs (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_save_valid_inputs) ... ok
test_set_stability_status (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_set_stability_status) ... ok
test_set_stored_values (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_set_stored_values) ... ok
test_update_software_parameters (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_update_software_parameters) ... ok
test_validate_inputs_allow_zero_false (tests.test_pid_tuning_tab.TestPidTuningTabUnit.test_validate_inputs_allow_zero_false) ... ok

----------------------------------------------------------------------
Ran 19 tests in 0.424s

OK
```

#### B. Runtime Method Execution Tracing
Trace via `sys.settrace` verified the execution of the following functions during the test run:
- `gui/pid_tuning_tab.py`:
  - `__init__`, `_build_ui`, `_build_hardware_pid_section`, `_build_stability_monitor_section`
  - `_on_read_from_arduino`, `_on_save_to_arduino`, `_on_update_software_params`
  - `validate_inputs`, `_set_error_feedback`, `_clear_error_feedback`
  - `set_stored_values`, `get_stored_values`, `set_stability_status`
  - Properties: `tolerance`, `settling_time`, `is_stable`, `last_error`
- `gui/main_window.py`:
  - `__init__`, `_build_ui`, `_start_worker`, `_stop_worker`, `_update_ui_state`
  - `_on_arduino_ready`, `_on_pid_received`, `_on_pid_send_command`
  - `_on_read_pid`, `_on_set_pid`, `_on_update_stability_params`

#### C. Empirical Stress & Randomized Value Verification
An independent harness evaluated 50 randomized float vectors (`0.0001 <= val <= 999.9999`) and boundary values:
- Verified exact 4-decimal formatting: `<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>`.
- Confirmed rejection of: `["nan", "NaN", "inf", "-inf", "Infinity", "-0.0001", "1000.01", "abc", "", "   ", "1.2.3"]`.
- Verified non-finite values displayed in stored gains show `"ERR"`.
- Verified disconnected state prevents transmission.

### 4. Prohibited Patterns Check

1. **Hardcoded test outputs**:
   Zero occurrences. Parsing and formatting code perform dynamic computations.
2. **Facade implementations**:
   Zero occurrences. All previous `print()` stubs have been replaced with full Qt signal/slot logic.
3. **Pre-populated artifacts**:
   Command: `find . -not -path '*/.*' -name '*.log' -o -name '*result*' -o -name '*output*'` returned 0 pre-populated result files.
4. **Self-certifying tests**:
   Tests independently create inputs and verify against protocol contracts.
5. **Mock bypasses in production**:
   Grep searches for `mock`, `fake`, `dummy`, `bypass` across `gui/` and `modules/` returned 0 matches.

---

## Adversarial Review & Caveats

1. **State Coherence on Disconnect**:
   In `MainWindow._stop_worker()`, `self._worker` is set to `None`, but `self._connected` is reset to `False` by `_on_serial_disconnected()` which is triggered asynchronously when the worker thread finishes and emits `self.disconnected`. If a test suite manually assigns a mock worker without connecting its `disconnected` signal, `self._connected` will not transition to `False`. This does not impact production operation with `SerialWorker`, but explicitly setting `self._connected = False` inside `_stop_worker()` would provide greater defensive consistency.
2. **Stability Monitor Loose Coupling**:
   `MainWindow._on_update_stability_params` safely checks `hasattr(self, "_stability_monitor")` before attempting method invocation, ensuring full decoupling until Requirement 2 is integrated.

---

## Verdict

**CLEAN**: All Milestone 2 requirements and forensic integrity checks pass with empirical evidence.
