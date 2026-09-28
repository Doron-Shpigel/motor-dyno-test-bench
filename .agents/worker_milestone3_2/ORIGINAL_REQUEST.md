## 2026-09-28T16:40:28Z
You are the Implementer (Worker) for Milestone 3 of the motor-dyno-test-bench project (replacing worker_milestone3_1).

Your assigned working directory is:
/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/worker_milestone3_2/

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Key Inputs:
1. Technical Analysis and Architecture Blueprint:
   /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/teamwork_preview_explorer_phase2_3/analysis.md
2. Project Spec and Contracts:
   /home/doron/Links/GitHub Folder/motor-dyno-test-bench/.agents/PROJECT.md
3. Current Source Files:
   - gui/main_window.py
   - gui/pid_tuning_tab.py
   - modules/serial_comm.py
   - modules/data_model.py
   - modules/csv_logger.py

Scope of Work for Milestone 3:
1. Implement `modules/stability_monitor.py`:
   - Pure-Python class `StabilityMonitor` with zero GUI dependencies.
   - Configurable parameters: `tolerance_pct: float = 2.0`, `settling_time_s: float = 1.5`, `min_abs_tolerance: float = 0.1`, `max_staleness_s: float = 0.5`.
   - Methods:
     - `set_parameters(tolerance_pct=None, settling_time_s=None, min_abs_tolerance=None)` (and alias `update_parameters`)
     - `add_reading(torque: float, timestamp: float | None = None)`
     - `is_stable(target_torque: float, current_time: float | None = None) -> bool`
     - `reset()`
     - Properties `tolerance_pct`, `settling_time_s`
   - Evaluation algorithm:
     - Check buffer not empty and latest reading not stale (now - t_latest <= max_staleness_s).
     - Buffer duration check: span >= settling_time_s.
     - Continuous tolerance band: all readings in [t_latest - settling_time_s, t_latest] must satisfy abs(val - target_torque) <= max(abs(target_torque) * (tolerance_pct / 100.0), min_abs_tolerance).
     - Memory pruning of readings older than max(3 * settling_time_s, 5.0).
2. Refactor `gui/main_window.py`:
   - Import `StabilityMonitor` and instantiate in `MainWindow.__init__` as `self._stability_monitor = StabilityMonitor()`.
   - Remove lines 220-226 in `_on_tick` (Phase 1 open-loop torque-to-DAC calculation `dac_raw = int(...)` and `SET:<dac>`).
   - Profile Stepping & Gating:
     - In `_on_start()`, initialize step index 0, set target torque from profile (`self._plf.torques[0]`), reset stability monitor, send `START` and `<SET_TORQUE:{target_torque:.2f}>`.
     - In `_on_data_received(torque, speed, dac)`, update `_last_torque`, `_last_speed`, `_last_dac`, `_last_rpm`, `_last_adc`, feed `self._stability_monitor.add_reading(torque, time.perf_counter())`, and update PID tab badge `set_stability_status(...)`.
     - In `_on_tick()`, evaluate `is_stable()`. If stable, advance to next waypoint `self._plf.torques[next_step]`, send `<SET_TORQUE:...>`, reset stability monitor, reset badge; if last waypoint completed, call `_on_stop()`. If not stable, check step timeout (`_step_timeout_s = 30.0`); if timed out, warn and advance.
     - Append authentic `Sample(elapsed_s=elapsed, torque_nm=self._last_torque, rpm=self._last_rpm, dac_raw=self._last_dac, adc_raw=self._last_adc)` to session, log to CSV, and update live readouts.
   - Synchronously set `self._connected = False` in `_stop_worker()`.
   - Wire `_worker.ack_received` to handle `ACK:SET_PID` and show status message.
   - Wire `_on_update_stability_params` to `self._stability_monitor.set_parameters(...)`.
3. Add `target_torque_nm: float = 0.0` to `Sample` in `modules/data_model.py` with default 0.0.
4. Comprehensive Automated Tests:
   - Create `tests/test_stability_monitor.py` covering all edge cases (empty buffer, duration, stability detection, noise spike breaking streak, zero torque floor, stale data, reset, parameter updates).
   - Create `tests/test_closed_loop_stepping.py` testing `MainWindow` profile stepping, setpoint transmission, stability gating, timeout fallback, authentic sample generation, and headless execution.
5. Verification:
   Run:
   `QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v`
   Ensure all 102+ tests pass with 0 failures and 0 errors.
6. Documentation & Handoff:
   Update `.agents/worker_milestone3_2/progress.md` and write a detailed `.agents/worker_milestone3_2/handoff.md` documenting modified files, tests created, and verification output. Send a completion message back to the orchestrator when finished.
