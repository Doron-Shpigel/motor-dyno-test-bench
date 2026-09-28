## 2026-09-28T16:53:25Z

You are the Implementer (Worker) for Milestone 4: Comprehensive E2E System Integration Verification of the motor-dyno-test-bench project.

Your assigned working directory is:
/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone4_1/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope of Work for Milestone 4:
1. Lifecycle & Stability Hardening (based on findings from Reviewer 2 & Challenger 2):
   - In `gui/main_window.py`:
     - In `_stop_worker()`: protect against re-entrancy / NoneType race:
       ```python
       def _stop_worker(self) -> None:
           self._connected = False
           worker = self._worker
           self._worker = None
           if worker is not None:
               worker.stop()
               worker.wait(3000)
       ```
     - In `_on_reset()`: ensure running sessions are stopped before resetting:
       ```python
       @pyqtSlot()
       def _on_reset(self) -> None:
           if self._session.state == RunState.RUNNING:
               self._on_stop()
           self._session.reset()
           ...
       ```
   - In `modules/stability_monitor.py`:
     - Add `math.isfinite()` validation in `set_parameters`:
       Reject non-finite / NaN / inf values for tolerance_pct, settling_time_s, min_abs_tolerance with `ValueError`.
     - In `is_stable()`: ensure inter-sample gaps within the settling window do not exceed `max_staleness_s`. Specifically, during reverse iteration of `self._readings`, verify that the difference between adjacent timestamps `(last_t - t) <= self._max_staleness_s`.
2. Implement Comprehensive E2E Integration Test Suite (`tests/test_e2e_integration.py`):
   - Test complete end-to-end user workflows using headless PyQt6 (`QApplication` offscreen) with a simulated Arduino firmware responder / mock serial transport:
     - **Test 1: Full Dyno Test Lifecycle E2E**:
       - Boot Arduino simulation → emits `DYNO_READY`.
       - GUI receives `DYNO_READY` → automatically queries `<GET_PID>`.
       - Arduino simulation responds `<PID_VALS:1.5000,0.1000,0.0500>`. GUI updates PID tab stored values.
       - User modifies PID parameters in PID tab to `Kp=2.2000, Ki=0.1500, Kd=0.0300` and clicks "Set PID on Arduino".
       - Verify GUI commands `<SET_PID:2.2000,0.1500,0.0300>`.
       - Arduino simulation sends `ACK:SET_PID:2.2000,0.1500,0.0300`.
       - User loads a test profile CSV with multiple waypoints (e.g. 0.0, 5.0, 10.0, 0.0 N·m).
       - User clicks Start: GUI commands `START` and `<SET_TORQUE:0.00>`.
       - Arduino simulation streams `<DATA:torque,speed,dac>` at 20 Hz.
       - At each waypoint, simulated Arduino PID loop converges to setpoint; `StabilityMonitor` detects stability; GUI automatically steps to next setpoint and commands `<SET_TORQUE:...>`.
       - Upon reaching the final setpoint, profile auto-stops, commands `STOP`, and session enters `RunState.FINISHED`.
       - Verify CSV log file is created in output directory, contains correct headers, and has genuine physical data rows matching the simulated Arduino stream.
       - User clicks Reset: session state returns to `IDLE`, live readouts reset, log path is cleared.
       - User disconnects: worker terminates cleanly with zero exceptions.
     - **Test 2: Emergency Disconnect & Abort Mid-Run**:
       - While profile is actively running, simulate unexpected serial disconnect or user abort.
       - Verify control loop timer stops, log file is flushed and closed cleanly, session state transitions properly, and no exceptions are raised.
     - **Test 3: Step Timeout & Stall Handling**:
       - Setpoint cannot settle within `_step_timeout_s`. Verify timeout triggers warning and advances to next waypoint or finishes cleanly without hanging.
     - **Test 4: Reset While Running Recovery**:
       - Trigger `_on_reset()` while running; verify logger is closed and subsequent start works with zero `RuntimeError`.
3. Verification:
   Run:
   `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v`
   Verify that ALL tests (217+ tests including the new E2E suite) pass with 0 failures and 0 errors.
4. Documentation & Handoff:
   Update `.agents/worker_milestone4_1/progress.md` and write `.agents/worker_milestone4_1/handoff.md`. Send a completion message when finished.
