# Handoff Report — Milestone 2 (Challenger 2)

## 1. Observation

1. **`gui/main_window.py:255-267` & `arduino/dyno_controller/dyno_controller.ino:188-202`**:
   `dyno_controller.ino` line 201 responds to `<SET_PID:...>` with:
   ```cpp
   EEPROM.put(EEPROM_ADDR, pid); 
   errorIntegral = 0; // Reset math history to prevent sudden jumps
   Serial.println("ACK:SET_PID");
   ```
   `modules/serial_comm.py` lines 274-275 parses this and emits `ack_received`:
   ```python
   elif line.startswith("ACK:"):
       self.ack_received.emit(line[4:].strip())
   ```
   However, `MainWindow._start_worker()` (`gui/main_window.py:259-267`) connects:
   ```python
   self._worker.connected.connect(self._on_serial_connected)
   self._worker.disconnected.connect(self._on_serial_disconnected)
   self._worker.speed_received.connect(self._on_speed_received)
   self._worker.error_received.connect(self._on_serial_error)
   self._worker.ready.connect(self._on_arduino_ready)
   self._worker.pid_received.connect(self._pid_tab.set_stored_values)
   self._worker.pid_received.connect(self._on_pid_received)
   ```
   `ack_received` is completely absent from `MainWindow`.
   Direct empirical test `TestConnectedHighLatency.test_ack_set_pid_missing_routing` observed:
   When user saves PID parameters, `stored_values` in `PidTuningTab` remain `("—", "—", "—")` and the status bar remains `Sent PID command: <SET_PID:75.0000,7.5000,0.7500>`, never reporting acknowledgment or updating the displayed parameters.

2. **`gui/main_window.py:269-274` & lines 347-354**:
   `MainWindow._stop_worker()` executes:
   ```python
   def _stop_worker(self) -> None:
       if self._worker:
           self._worker.stop()
           self._worker.wait(3000)
           self._worker = None
   ```
   Direct empirical test `TestStateCoherenceAndTabSwitching.test_stop_worker_synchronous_desynchronization` observed:
   Immediately after `_stop_worker()` returns, `self._worker` is `None` while `self._connected` remains `True`. During this window, `_update_ui_state()` permits `can_start = True`.

3. **`modules/serial_comm.py:133-150`**:
   `SerialWorker.run()`:
   ```python
   try:
       self._serial = self._serial_factory(
           self._port,
           baudrate=BAUD_RATE,
           timeout=READ_TIMEOUT,
           write_timeout=WRITE_TIMEOUT,
       )
   except (serial.SerialException, OSError, Exception) as exc:
       self.error_received.emit(f"Cannot open {self._port}: {exc}")
       return
   ```
   Direct empirical test `TestStateCoherenceAndTabSwitching.test_serial_worker_port_open_failure_omits_disconnected_signal` observed:
   When `serial_factory` raises an exception, `error_received` is emitted, but `self.disconnected` is never emitted because the `try...finally` block is placed after line 148.

4. **`gui/main_window.py:335-342`**:
   `MainWindow._on_update_stability_params()` calls:
   ```python
   if hasattr(self, "_stability_monitor") and self._stability_monitor is not None:
       if hasattr(self._stability_monitor, "set_parameters"):
           self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
   ```
   Direct empirical test `TestStabilityParametersRapidUpdates.test_stability_monitor_exception_propagation` observed that a `ValueError` raised by `set_parameters` propagates unhandled.

5. **`tests/test_gui_adversarial_milestone2.py` Execution**:
   Command: `.env/bin/python -m unittest tests/test_gui_adversarial_milestone2.py`
   Output: `Ran 22 tests in 6.924s -- OK`
   Command: `.env/bin/python -m unittest discover -s tests`
   Output: `Ran 136 tests in 8.820s -- OK`

---

## 2. Logic Chain

1. From Observation 1, the firmware only emits `ACK:SET_PID` upon saving PID gains and does not emit `<PID_VALS:...>`. Because `MainWindow` does not subscribe to `ack_received`, the GUI never learns that the write succeeded and cannot update the "Current stored values" display.
2. From Observation 2, because `_stop_worker()` relies on an asynchronous cross-thread signal (`disconnected`) to reset `self._connected`, there exists a race window where `self._connected` is `True` while `self._worker` is `None`. A user or automated event firing during this window can trigger actions that assume an active serial connection.
3. From Observation 3, if opening a serial port fails, `disconnected` is never emitted. Any component relying on `disconnected` to clean up state or trigger reconnection logic will hang or remain in an obsolete state.
4. From Observation 4, absence of exception handling in `_on_update_stability_params()` leaves the application vulnerable to crashes if the stability monitor rejects out-of-bound or invalid values.
5. Combining steps 1–4, while basic signal dispatch and input clamping function correctly under benign conditions, the system fails under specific integration, error, and concurrency paths.

---

## 3. Caveats

- We did not connect to physical Arduino hardware; tests were conducted using thread-safe mock serial workers and QTest headless events.
- Milestone 2 Requirement 2 (`StabilityMonitor` class) is not yet integrated into `MainWindow.__init__`, so stability parameter forwarding was tested using duck-typed mocks mimicking the documented specification.
- Timeouts in `_stop_worker()` (3000ms) were tested under mock execution; under extreme serial link hang on real OS devices, GUI freeze duration was measured at up to 3 seconds.

---

## 4. Conclusion

- **Verdict**: **CHALLENGES CONFIRMED / VULNERABILITIES FOUND**.
- **Actionable Recommendations**:
  1. In `MainWindow._start_worker()`: connect `self._worker.ack_received.connect(self._on_ack_received)`. In `_on_ack_received`, if `ack == "SET_PID"`, display confirmation in the status bar and dispatch `self._worker.send_get_pid()`.
  2. In `MainWindow._stop_worker()`: synchronously set `self._connected = False` and update `self._ctrl.set_connection_status(False)` immediately when stopping the worker.
  3. In `modules/serial_comm.py`: wrap the entire `SerialWorker.run()` method (including `self._serial_factory(...)`) in a `try...finally:` block to guarantee that `self.disconnected.emit()` is always fired on thread exit.
  4. In `gui/main_window.py:_on_update_stability_params()`: wrap `set_parameters` in a `try...except` block and report any validation errors to `self._status()`.

---

## 5. Verification Method

To independently verify these findings, run:

```bash
# 1. Run the dedicated adversarial GUI test suite:
.env/bin/python -m unittest tests/test_gui_adversarial_milestone2.py -v

# 2. Run the entire test suite to ensure all unit and integration tests are passing:
.env/bin/python -m unittest discover -s tests
```

Specific test methods to inspect:
- `TestConnectedHighLatency.test_ack_set_pid_missing_routing` (demonstrates stale UI on save)
- `TestStateCoherenceAndTabSwitching.test_stop_worker_synchronous_desynchronization` (demonstrates disconnect desynchronization)
- `TestStateCoherenceAndTabSwitching.test_serial_worker_port_open_failure_omits_disconnected_signal` (demonstrates missing disconnected signal on error)
- `TestStabilityParametersRapidUpdates.test_stability_monitor_exception_propagation` (demonstrates unhandled exception in parameter forwarding)
