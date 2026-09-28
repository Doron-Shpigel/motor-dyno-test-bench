# Handoff Report: Stability Monitor & Closed-Loop Control (Requirement 2)

**Explorer**: Explorer 3 (Stability Monitor Explorer)  
**Assigned Directory**: `.agents/teamwork_preview_explorer_phase2_3/`  
**Handoff Type**: Hard (Task Complete)

---

## 1. Observation

1. **Open-Loop Math in `gui/main_window.py` (lines 216–222)**:
   ```python
   # DAC value
   dac_raw = int(
       min(max(torque_nm / self._calibration.max_torque_nm, 0.0), 1.0) * 4095
   )
   if self._worker:
       self._worker.send_command(f"SET:{dac_raw}")
   ```
   Observed that the PC computes a synthetic DAC value using a linear assumption against `self._calibration.max_torque_nm` and sends `SET:<dac_raw>`.

2. **Arduino Closed-Loop PID Firmware in `arduino/dyno_controller/dyno_controller.ino`**:
   - Lines 87–129: Hardware PID loop executes every 20ms (`PID_INTERVAL = 20`), reading `currentTorque = (float)analogRead(TORQUE_PIN)` and writing `mcp4725_write(dacValue)`.
   - Lines 134–142: Firmware transmits telemetry every 50ms (20 Hz):
     ```c
     Serial.print("<DATA:");
     Serial.print(currentTorque, 2); Serial.print(",");
     Serial.print(currentSpeed, 2); Serial.print(",");
     Serial.print(dacValue);
     Serial.println(">");
     ```
   - Lines 204–210: Firmware parses closed-loop setpoint commands:
     ```c
     else if (cmd.startsWith("<SET_TORQUE:")) {
       int startIdx = cmd.indexOf(':') + 1;
       int endIdx = cmd.indexOf('>', startIdx);
       targetTorque = cmd.substring(startIdx, endIdx).toFloat();
       Serial.print("ACK:SET_TORQUE:");
       Serial.println(targetTorque);
     }
     ```
   - The Arduino no longer accepts or processes `SET:<dac_raw>` commands.

3. **Steady-State Parameters in `gui/pid_tuning_tab.py`**:
   - Lines 199–222:
     - `self._tolerance_spin`: `QDoubleSpinBox`, range 0.1 to 50.0%, default 2.0%.
     - `self._settling_spin`: `QDoubleSpinBox`, range 0.1 to 60.0s, default 1.5s.
   - Lines 233–242 & 268–284:
     - `self._status_label`: QLabel displaying `"WAITING"` (amber background `#313244`) or `"STABLE"` (green background `#1e4a2a`).
     - `set_stability_status(stable: bool)`: already implemented to toggle between STABLE and WAITING styling.
   - Lines 297–303:
     - `_on_update_software_params()`: currently a `print()` stub that does not emit any signals to `MainWindow`.

4. **Continuous Linear Interpolation in `modules/plf.py` and `gui/main_window.py`**:
   - In `modules/plf.py` lines 104–114:
     ```python
     def torque_at(self, time_s: float) -> float:
         ...
         return float(np.interp(time_s, self.times, self.torques))
     ```
   - In `gui/main_window.py` lines 206–214:
     ```python
     elapsed = self._session.elapsed_seconds()
     if elapsed > self._plf.duration:
         self._on_stop()
         return
     torque_nm = self._plf.torque_at(elapsed)
     ```
   - Profile elapsed time was strictly tied to wall-clock time (`time.perf_counter() - self._start_time`), and `torque_at(elapsed)` interpolated setpoints continuously every 100ms.

5. **Sample, Data Model, and CSV Logger**:
   - `modules/data_model.py` lines 24–32:
     `Sample(elapsed_s, torque_nm, rpm, dac_raw, adc_raw)`
   - `gui/main_window.py` lines 226–233:
     `sample = Sample(elapsed_s=elapsed, torque_nm=torque_nm, rpm=rpm, dac_raw=dac_raw, adc_raw=self._last_adc)`
     Observed that `torque_nm` was theoretical PLF setpoint, and `dac_raw` was synthetic open-loop calculation.
   - `modules/csv_logger.py` line 19:
     `FIELDNAMES = ["elapsed_s", "torque_nm", "rpm", "dac_raw", "adc_raw"]`

6. **Python Execution Environment**:
   - Project environment at `.env/bin/python` verified working with PyQt6, pyqtgraph, serial, and numpy via:
     `.env/bin/python -c "import PyQt6, pyqtgraph, serial, numpy; print('Imports OK')"`
   - Headless execution confirmed working via `QT_QPA_PLATFORM=offscreen .env/bin/python`.
   - Python standard `unittest` test runner verified functional.

---

## 2. Logic Chain

1. **Need to Eliminate Open-Loop Math (Supported by Observations 1 & 2)**:
   - Because the Arduino firmware now operates its own 50 Hz closed-loop PID control and only listens to `<SET_TORQUE:t>`, the PC sending `SET:<dac>` is completely ignored by the hardware.
   - Therefore, lines 216–222 in `gui/main_window.py` must be completely removed and replaced with `<SET_TORQUE:target_torque>`.

2. **Placement of Stability Monitor in `modules/stability_monitor.py` (Supported by Observations 2 & 6)**:
   - To adhere to `PROJECT.md` modularity and enable fast headless unit testing, steady-state evaluation logic must be separated from PyQt6 GUI widgets.
   - Placing `StabilityMonitor` in `modules/stability_monitor.py` ensures 100% testability with zero GUI dependencies.

3. **Steady-State Gating & Mathematical Condition (Supported by Observations 2, 3, & 4)**:
   - The stability condition requires measured torque to remain within $\pm\text{tolerance}\%$ of target torque continuously for $\ge\text{settling\_time}$ seconds.
   - If setpoint torque $T(t)$ interpolates continuously during a ramp, target torque shifts every 100ms (e.g., $1.5\text{ N}\cdot\text{m}$ over $1.5\text{ s}$). A stability monitor checking if torque remained within $\pm 2\%$ ($0.05\text{ N}\cdot\text{m}$) of the *current* setpoint over the past $1.5\text{ s}$ would suffer from mathematical deadlock and never report stability.
   - Therefore, dynamometer profile progression must follow a **Discrete Waypoint Step-and-Hold Model**:
     The profile steps through discrete waypoints $(\tau_0, \tau_1, \dots, \tau_k)$ from `self._plf.torques`.
     At step $i$, target torque $\tau_i$ is held until `StabilityMonitor.is_stable(\tau_i)` returns `True`.
     Only upon reaching stability does the control loop advance to step $i+1$ (or stop if at the final waypoint).
   - At zero setpoint ($T_{\text{target}} = 0.0\text{ N}\cdot\text{m}$), $\Delta = \max(|T_{\text{target}}| \cdot \text{tol}\%, \Delta_{\min})$, where $\Delta_{\min} = 0.1\text{ N}\cdot\text{m}$, preventing an impossible zero-width tolerance band due to ADC sensor noise.

4. **Authentic Telemetry Propagation (Supported by Observations 2 & 5)**:
   - When incoming `<DATA:torque,speed,dac>` packets arrive at 20 Hz, `MainWindow._on_data_received` saves `_last_torque`, `_last_speed`, and `_last_dac`.
   - Feeding authentic `_last_torque` into `Sample.torque_nm` and `_last_dac` into `Sample.dac_raw` ensures that `DynoSession`, `CSVLogger`, `ControlPanel`, and `PlotPanel` all present authentic physical measurements without requiring any schema modifications to `Sample` or `CSVLogger`.

5. **UI Wiring (Supported by Observation 3)**:
   - `PidTuningTab` should emit `sig_update_stability_params(tol, settle)` when "Update Software Parameters" is clicked, calling `StabilityMonitor.set_parameters(tol, settle)`.
   - `MainWindow` updates the PID tab status badge via `set_stability_status(is_stable)` in real-time.

---

## 3. Caveats

1. **Step Timeout Safety**: If a dyno motor cannot reach the setpoint or PID oscillates, `is_stable()` will never return `True`. A step timeout (e.g. 30 seconds) must be configured in `MainWindow` to prevent the dyno from holding stall/brake torque indefinitely.
2. **Torque Sensor Calibration**: In `dyno_controller.ino`, `currentTorque = (float)analogRead(TORQUE_PIN)`. In the current firmware sketch, raw ADC is emitted directly. If the physical load cell amplifier produces a calibrated analog voltage, calibration scaling between ADC counts and N·m should match the hardware spec.
3. **PLF Format Assumption**: We assume user CSV profiles contain monotonic time/torque waypoints as exemplified in `assets/example_profile.csv`.

---

## 4. Conclusion

1. **Remove Lines 216–222 in `gui/main_window.py`**: Eradicate `dac_raw = int(...)` and `SET:<dac_raw>`. Send `<SET_TORQUE:{target_torque:.2f}>` to command the Arduino's internal PID loop.
2. **Implement `modules/stability_monitor.py`**: Implement a bounded rolling `deque` buffer checking that all samples in the time window $[t_{\text{latest}} - T_{\text{settle}}, t_{\text{latest}}]$ fall within $[T_{\text{target}} \pm \Delta_{\text{band}}]$, with staleness protection and zero-torque handling.
3. **Adopt Waypoint Step-and-Hold Profile Stepping**: Drive the dyno profile through discrete PLF waypoints, gating transition to step $i+1$ on `StabilityMonitor.is_stable()`.
4. **Log Authentic Physical Telemetry**: Ingest `<DATA:t,s,d>` in `_on_data_received`, recording measured load-cell torque in `Sample.torque_nm` and real Arduino DAC output in `Sample.dac_raw`.
5. **Wire `PidTuningTab`**: Connect `sig_update_stability_params` to `StabilityMonitor.set_parameters`, and push real-time stability booleans to `set_stability_status()`.

---

## 5. Verification Method

### 5.1 Unit Verification of `StabilityMonitor`
Execute the unit test suite covering stability detection, tolerance boundaries, streak reset, zero torque, and staleness:
```bash
.env/bin/python -m unittest tests/test_stability_monitor.py -v
```

### 5.2 Integration Verification of Profile Stepping
Execute the headless PyQt6 integration test suite:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_closed_loop_stepping.py -v
```
**Verification Checks**:
1. Confirm `<SET_TORQUE:...>` is queued when a step starts.
2. Confirm step index does **not** advance while simulated torque telemetry remains outside tolerance.
3. Confirm step index advances immediately after simulated torque telemetry remains within tolerance for $\ge 1.5\text{ s}$.
4. Confirm `Sample` and CSV logs contain authentic measured torque values and DAC values.
5. Confirm `PidTuningTab` status label toggles accurately between `"WAITING"` and `"STABLE"`.

### 5.3 Invalidation Conditions
The conclusion is invalidated if:
- The Arduino firmware is reverted back to open-loop `SET:<dac>` commands.
- Continuous ramp testing without step plateaus is mandated, in which case a tracking error formulation rather than steady-state settling time must be defined.
