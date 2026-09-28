# Changes Summary: Milestone 2 Requirement 3 (PID UI Wire to Serial Commands)

## Modified Files

### 1. `gui/pid_tuning_tab.py`
- **Signals**:
  - Added `sig_read_pid = pyqtSignal()`.
  - Added `sig_set_pid = pyqtSignal(float, float, float)`.
  - Added `sig_send_command = pyqtSignal(str)`.
  - Added `sig_update_stability_params = pyqtSignal(float, float)`.
- **Constructor**:
  - Added optional `command_sender: Callable[[str], None] | None = None`.
  - Initialized `self._command_sender = command_sender`.
  - Initialized `self._last_error: str | None = None`.
- **UI Feedback**:
  - Added non-blocking inline `self._feedback_label` under input parameters grid.
- **Input Validation**:
  - Added `validate_inputs(self, allow_zero: bool = True) -> tuple[float, float, float] | None`:
    - Checks non-empty/non-whitespace text.
    - Parses float and catches `ValueError`.
    - Checks `math.isfinite(val)` to reject `NaN`, `Inf`, `-Inf`.
    - Enforces non-negative values (`val >= 0.0`) while permitting `0.0` for PI/PD configurations.
    - Rejects values exceeding `1000.0` safety limit matching firmware.
    - Sets error message in `self._last_error` and `self._feedback_label`.
- **Action Slots**:
  - Implemented `_on_read_from_arduino(self)`: emits `sig_read_pid` and `sig_send_command("<GET_PID>")`, calls `_command_sender` if present.
  - Implemented `_on_save_to_arduino(self)`: calls `validate_inputs()`; if valid, formats `<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>`, emits `sig_set_pid(kp, ki, kd)` and `sig_send_command(cmd)`, calls `_command_sender` if present.
  - Implemented `_on_update_software_params(self)`: reads `_tolerance_spin` and `_settling_spin` and emits `sig_update_stability_params(tolerance, settling_time)`.
- **Display & Properties**:
  - Hardened `set_stored_values(kp, ki, kd)` against non-finite values (displays `"ERR"` if non-finite).
  - Added `get_stored_values(self) -> tuple[str, str, str]`.
  - Added properties: `tolerance`, `settling_time`, `is_stable`, `last_error`.

### 2. `gui/main_window.py`
- **UI Wiring**:
  - In `_build_ui()`: connected `self._pid_tab.sig_send_command.connect(self._on_pid_send_command)` and `self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)`.
- **Worker Signal Wiring**:
  - In `_start_worker()`:
    - Connected `self._worker.ready.connect(self._on_arduino_ready)`.
    - Connected `self._worker.pid_received.connect(self._pid_tab.set_stored_values)`.
    - Connected `self._worker.pid_received.connect(self._on_pid_received)`.
- **Slots Added**:
  - `_on_arduino_ready()`: logs status and calls `self._worker.send_get_pid()` to auto-populate stored gains on connection.
  - `_on_pid_received(kp, ki, kd)`: updates status bar message.
  - `_on_pid_send_command(cmd)`: forwards command to `self._worker.send_command(cmd)` if connected; displays warning if disconnected.
  - `_on_read_pid()` and `_on_set_pid(kp, ki, kd)`: helper slots routing to `_on_pid_send_command`.
  - `_on_update_stability_params(tol, settle)`: updates status bar and forwards to `_stability_monitor` if present.

### 3. `tests/test_pid_tuning_tab.py`
- Created comprehensive automated test suite (19 test cases):
  - `TestPidTuningTabUnit`:
    - `test_default_state`: verifies defaults, spinboxes, status badge, properties.
    - `test_read_button_emits_signals`: verifies `sig_read_pid` and `sig_send_command("<GET_PID>")`.
    - `test_read_button_with_command_sender`: verifies optional callback invocation.
    - `test_save_valid_inputs`: verifies `sig_set_pid` and `sig_send_command("<SET_PID:p,i,d>")` with 4 decimals.
    - `test_save_boundary_values`: verifies 0.0 and 1000.0 boundaries.
    - `test_save_invalid_inputs_comprehensive`: 18 adversarial test cases covering negatives, out-of-range (>1000), non-numeric text, empty/whitespace strings, `nan`, `inf`, `-inf`, `Infinity`.
    - `test_validate_inputs_allow_zero_false`: verifies `allow_zero=False` behavior.
    - `test_update_software_parameters`: verifies `sig_update_stability_params(tol, settle)`.
    - `test_set_stored_values`: verifies 4-decimal formatting and non-finite `"ERR"` guard.
    - `test_set_stability_status`: verifies `"STABLE"` vs `"WAITING"` label and stylesheet updates.
  - `TestMainWindowPidIntegration`:
    - `test_read_pid_routing_when_connected`: verifies command sent to mock worker and status update.
    - `test_read_pid_routing_when_disconnected`: verifies no transmission when disconnected and warning status.
    - `test_save_pid_routing_when_connected`: verifies `<SET_PID:...>` sent to mock worker.
    - `test_save_pid_routing_when_disconnected`: verifies no transmission when disconnected.
    - `test_direct_pid_helper_slots`: verifies `_on_read_pid` and `_on_set_pid`.
    - `test_telemetry_updates_pid_tab`: verifies `pid_received` updates stored values in tab.
    - `test_arduino_ready_triggers_auto_query`: verifies auto-query of PID on ready.
    - `test_software_stability_update_routing`: verifies forwarding to `_stability_monitor`.
    - `test_start_worker_wires_pid_and_ready_signals`: verifies `_start_worker` signal connections.

### 4. `tests/__init__.py`, `tests/test_adversarial_boundary.py`, `tests/test_serial_adversarial.py`, `tests/test_serial_comm.py`
- Initialized `QApplication` instance so that both QWidget GUI test suites and QThread background tests run together in a single unittest discover runner without conflicting with QCoreApplication singletons.

## Verification
- Unit & integration tests:
  `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_pid_tuning_tab.py -v` (19/19 passed)
- Full project test suite:
  `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v` (102/102 passed, 0 failures, 0 errors)
