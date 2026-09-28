# Adversarial Challenge Report — Milestone 2 (Challenger 2)

**Evaluator**: Challenger 2 (Empirical Challenger)  
**Target Scope**: GUI Signal Routing, Concurrency, and State Handling between `gui/pid_tuning_tab.py`, `gui/main_window.py`, and `modules/serial_comm.py`  
**Verdict**: **CHALLENGES CONFIRMED / VULNERABILITIES FOUND**

---

## Executive Summary

Adversarial testing was executed against the Milestone 2 PID & Stability GUI integration using an empirical test harness (`tests/test_gui_adversarial_milestone2.py`) running on Python 3.12 (`.env/bin/python`).

All 4 targeted task domains were subjected to stress tests, race condition injectors, and failure simulations:
1. Rapid clicking of "Read from Arduino" and "Save to Arduino" while disconnected.
2. Rapid clicking while connected with high latency and slow I/O.
3. Concurrent and interleaved triggering of `_on_arduino_ready` and `pid_received`.
4. Rapid updates to stability parameters and external monitor forwarding.

### Summary of Empirical Findings
- **Critical Flaw 1 (ACK Handling Missing)**: `MainWindow` fails to connect or handle `ack_received("SET_PID")`. When the operator clicks "Save to Arduino", the Arduino firmware updates EEPROM and responds with `ACK:SET_PID\n` (per `dyno_controller.ino:201`). Because `ack_received` is unhandled and `<PID_VALS:...>` is not sent on write, the "Current stored values" fields in the GUI are **never updated**, and the status bar permanently displays `"Sent PID command: <SET_PID:...>"` without confirmation of success.
- **High Risk 2 (Disconnect State Desynchronization Window)**: `MainWindow._stop_worker()` nullifies `self._worker` immediately but fails to reset `self._connected = False` synchronously. This creates an inconsistent state where `_connected == True` while `_worker is None`, allowing `can_start` to permit starting the control loop without a physical worker.
- **High Risk 3 (`SerialWorker` Missing `disconnected` Signal on Port Open Failure)**: In `modules/serial_comm.py:137-147`, when `serial_factory` raises an exception during port opening, the worker thread emits `error_received` and executes `return` before entering the `try...finally` block. `disconnected.emit()` is **never emitted**, leaving callers and UI state stuck.
- **Medium Risk 4 (High-Latency Queue Flooding & GUI Freeze)**: PID Tab buttons have no in-flight disable guards. Rapid clicking under high latency queues unbounded commands. `SerialWorker.run()`'s drain loop does not check `self._stop_requested`, causing `_stop_worker()`'s `wait(3000)` to freeze the GUI thread for up to 3 seconds upon disconnect.
- **Medium Risk 5 (Uncaught Exception in Stability Monitor Forwarding)**: `MainWindow._on_update_stability_params()` forwards parameters to `_stability_monitor.set_parameters()` without a `try...except` block. Any exception raised by the monitor crashes the event handler.

---

## Detailed Challenges & Empirical Verification

### Challenge 1 (Critical): Missing `ACK:SET_PID` Handling Leaves Stored PID Values Stale & Unconfirmed

- **Assumption Challenged**: Saving PID parameters from the GUI automatically updates the displayed "Current stored values" and confirms EEPROM write success.
- **Attack Scenario**:
  1. User enters Kp=75.0, Ki=7.5, Kd=0.75 and clicks "Save to Arduino".
  2. `MainWindow._on_pid_send_command` sends `<SET_PID:75.0000,7.5000,0.7500>`.
  3. Firmware receives command, saves to EEPROM, and replies: `ACK:SET_PID\n` (`dyno_controller.ino:201`).
  4. `SerialWorker._parse_line` emits `self.ack_received.emit("SET_PID")` (`serial_comm.py:275`).
  5. `MainWindow._start_worker()` only connects `pid_received`, `speed_received`, `ready`, `connected`, `disconnected`, and `error_received`. `ack_received` is completely unconnected.
- **Empirical Evidence**:
  Executed `TestConnectedHighLatency.test_ack_set_pid_missing_routing`:
  - Result: `tab.get_stored_values()` remained `("—", "—", "—")`.
  - Status bar remained stuck on `"Sent PID command: <SET_PID:75.0000,7.5000,0.7500>"`.
  - Stored values are only updated if the user manually presses "Read from Arduino" or if Arduino sends `<PID_VALS:...>`.
- **Blast Radius**: Operator confusion and inability to know whether PID gains took effect or failed in EEPROM.
- **Mitigation**:
  In `MainWindow._start_worker()`: connect `self._worker.ack_received.connect(self._on_ack_received)`. In `_on_ack_received(ack_cmd)`:
  - If `ack_cmd == "SET_PID"`, display `"PID gains successfully saved to Arduino EEPROM."` in the status bar and dispatch `self._worker.send_get_pid()` to query and refresh the displayed values.

---

### Challenge 2 (High): `_stop_worker()` State Desynchronization Window

- **Assumption Challenged**: Stopping the serial worker synchronously transitions the application to a disconnected state.
- **Attack Scenario**:
  1. `MainWindow._stop_worker()` runs:
     ```python
     def _stop_worker(self) -> None:
         if self._worker:
             self._worker.stop()
             self._worker.wait(3000)
             self._worker = None
     ```
  2. Notice that `_stop_worker()` does NOT set `self._connected = False` or update `self._ctrl`. It waits for `self.disconnected` signal to arrive at `_on_serial_disconnected`.
  3. Because cross-thread signals in Qt are queued, immediately after `_stop_worker()` returns, `self._worker` is `None` while `self._connected` is still `True`.
- **Empirical Evidence**:
  Executed `TestStateCoherenceAndTabSwitching.test_stop_worker_synchronous_desynchronization`:
  - Immediately after `_stop_worker()`: `self.window._worker is None` is `True`, but `self.window._connected` is still `True`.
  - During this window, `self._update_ui_state()` computes `can_start = True`. Clicking Start launches a run session with a non-existent worker.
- **Blast Radius**: Run state corruption; timer ticks without serial worker; logging empty samples.
- **Mitigation**:
  Set `self._connected = False` and call `self._ctrl.set_connection_status(False)` directly inside `_stop_worker()`.

---

### Challenge 3 (High): `SerialWorker` Never Emits `disconnected` on Port Open Failure

- **Assumption Challenged**: `SerialWorker` always emits `disconnected` whenever its thread finishes execution.
- **Attack Scenario**:
  1. Look at `modules/serial_comm.py:137-147`:
     ```python
     try:
         self._serial = self._serial_factory(...)
     except (serial.SerialException, OSError, Exception) as exc:
         self.error_received.emit(f"Cannot open {self._port}: {exc}")
         return
     ```
  2. The `try...finally:` block containing `self.disconnected.emit()` only starts at line 148.
  3. If opening the serial port throws an exception, the thread returns early at line 146.
- **Empirical Evidence**:
  Executed `TestStateCoherenceAndTabSwitching.test_serial_worker_port_open_failure_omits_disconnected_signal`:
  - `error_received` emitted: 1
  - `disconnected` emitted: 0
- **Blast Radius**: Any logic relying on `disconnected` signal for lifecycle cleanup or reconnect handling fails to execute.
- **Mitigation**:
  Enclose the port opening inside the outer `try...finally` block in `SerialWorker.run()`, ensuring `self.disconnected.emit()` is always called on thread exit.

---

### Challenge 4 (Medium): High-Latency Command Flooding & GUI Freeze on Disconnect

- **Assumption Challenged**: Rapid clicking of PID buttons is safe under high-latency serial links.
- **Attack Scenario**:
  1. User rapidly clicks "Read from Arduino" or "Save to Arduino" 50 times during network/serial lag.
  2. `SerialWorker.send_command()` queues all 50 commands into `queue.Queue()`.
  3. In `SerialWorker.run()`:
     ```python
     while not self._queue.empty():
         cmd = self._queue.get_nowait()
         self._serial.write(f"{cmd}\n".encode())
     ```
     `self._stop_requested` is NOT checked inside this draining loop.
  4. If user clicks "Disconnect", `_stop_worker()` calls `self._worker.wait(3000)`.
  5. The main GUI thread freezes for up to 3 seconds waiting for the worker to drain or join.
- **Empirical Evidence**:
  Tested in `TestConnectedHighLatency.test_rapid_read_high_latency_burst` and `test_rapid_clicks_then_immediate_disconnect`.
- **Blast Radius**: GUI unresponsiveness, potential serial buffer overflow on microcontrollers.
- **Mitigation**:
  1. Add debouncing or disable buttons until response/timeout occurs (`self._read_btn.setEnabled(False)`).
  2. Check `if self._stop_requested: break` inside `while not self._queue.empty():`.

---

### Challenge 5 (Medium): Missing Exception Guard in Stability Parameter Forwarding

- **Assumption Challenged**: Forwarding parameters to `_stability_monitor` is safe from unhandled exceptions.
- **Attack Scenario**:
  `MainWindow._on_update_stability_params()` calls:
  ```python
  if hasattr(self, "_stability_monitor") and self._stability_monitor is not None:
      if hasattr(self._stability_monitor, "set_parameters"):
          self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
  ```
  If `set_parameters` raises a `ValueError` or `TypeError`, it propagates directly out of the Qt slot.
- **Empirical Evidence**:
  Executed `TestStabilityParametersRapidUpdates.test_stability_monitor_exception_propagation`:
  - `ValueError` was raised and unhandled.
- **Blast Radius**: Unhandled exception crashes the GUI event loop.
- **Mitigation**:
  Wrap the invocation in a `try...except Exception as exc:` block and display an error message in `self._status()` or `_show_error()`.

---

## Stress Test Results Summary

| Test Case | Objective | Condition | Actual Behavior | Result |
|---|---|---|---|---|
| `test_rapid_read_while_disconnected` | 300 rapid clicks on Read | Disconnected | No crash, status bar displays disconnected | **PASS** |
| `test_rapid_save_valid_inputs_while_disconnected` | 300 rapid clicks on Save | Disconnected | Validated locally, blocked from sending | **PASS** |
| `test_rapid_save_invalid_inputs_while_disconnected` | 300 clicks with negative values | Disconnected | Rejected by `validate_inputs()`, error feedback displayed | **PASS** |
| `test_rapid_clicks_during_boot_delay_transition` | Clicks during boot delay | Worker starting | Commands safely rejected with disconnected status | **PASS** |
| `test_rapid_read_high_latency_burst` | 50 rapid reads with 10ms I/O delay | Connected | 50 commands queued in FIFO order | **PASS** |
| `test_rapid_save_with_rapidly_mutating_inputs` | 20 rapid saves with changing Kp | Connected | Commands queued in exact order | **PASS** |
| `test_ack_set_pid_missing_routing` | Firmware returns `ACK:SET_PID` | Connected | Stored values stay stale ("—"), no ACK confirmation | **CONFIRMED FLAW** |
| `test_multithreaded_concurrent_ready_and_pid_emissions` | Concurrent `ready` + `pid_received` | 2 threads | Qt queued signal-slot safely serialized execution | **PASS** |
| `test_interleaved_ready_and_pid_received_storm` | 200 interleaved ready/pid pairs | Connected | 200 GET_PID commands dispatched, stored values match last PID | **PASS** |
| `test_pid_received_with_edge_values` | 0.0, 1000.0, sub-decimals | Connected | Formatted with 4 decimal precision | **PASS** |
| `test_rapid_stability_parameter_updates` | 500 rapid stability updates | Running GUI | 500 signals emitted, spinbox values accurate | **PASS** |
| `test_stability_parameters_boundary_clamping` | -10.0 and 999.0 inputs | Spinbox | Clamped to [0.1, 50.0] and [0.1, 60.0] | **PASS** |
| `test_stability_monitor_exception_propagation` | Monitor raises `ValueError` | Update click | Exception propagates unhandled | **CONFIRMED FLAW** |
| `test_tab_switching_preserves_signal_routing` | Switch between tab 0 and tab 1 | Idle | Signals cleanly delivered across tab switches | **PASS** |
| `test_stop_worker_synchronous_desynchronization` | Synchronous state check after stop | Disconnect | `_connected` remains True while `_worker` is None | **CONFIRMED FLAW** |
| `test_serial_worker_port_open_failure_omits_disconnected_signal` | Port open failure in worker | Startup | `disconnected` signal never emitted | **CONFIRMED FLAW** |

Total tests in suite: **22 tests**  
All tests passing in `.env/bin/python -m unittest tests/test_gui_adversarial_milestone2.py` (which includes assertions capturing the exact flawed states).
