# Phase 2 Technical Analysis: Stability Monitor & Closed-Loop Control (Requirement 2)

**Explorer**: Explorer 3 (Stability Monitor Explorer)  
**Date**: 2026-09-28  
**Scope**: Requirement 2 (R2) — Stability Monitor, Closed-Loop Control Loop, Profile Stepping, and Authentic Telemetry Flow in `gui/main_window.py`.

---

## 1. Executive Summary

This report provides a comprehensive architectural investigation into replacing the Phase 1 open-loop torque-to-DAC math in `gui/main_window.py` with an authentic closed-loop control system. We design a dedicated, decoupled `StabilityMonitor` module (`modules/stability_monitor.py`) employing a rolling buffer to evaluate physical steady-state settling criteria ($\pm\text{tolerance}\%$ for continuous $\ge\text{settling\_time}$ seconds). Furthermore, we resolve the architectural conflict between continuous PLF interpolation and steady-state settling by specifying a waypoint step-and-hold profile execution engine. Finally, we establish the end-to-end data pipeline ensuring `Sample`, `DynoSession`, `CSVLogger`, and UI readouts reflect genuine physical load-cell and DAC telemetry rather than open-loop mathematical approximations.

---

## 2. Requirement 1: Open-Loop Math Removal

### 2.1 Current Implementation (Phase 1)
In `gui/main_window.py`, lines 216–222 execute open-loop torque-to-DAC conversion inside `MainWindow._on_tick`:

```python
# Lines 216-222 in gui/main_window.py
# DAC value
dac_raw = int(
    min(max(torque_nm / self._calibration.max_torque_nm, 0.0), 1.0) * 4095
)
if self._worker:
    self._worker.send_command(f"SET:{dac_raw}")
```

#### Flaws in Phase 1 Architecture:
1. **Uncalibrated Linear Assumption**: Phase 1 assumes that DAC output voltage maps linearly to brake torque (`torque_nm / max_torque_nm * 4095`). In actual eddy-current or hysteresis dynamometers, magnetic brake torque varies non-linearly with coil excitation current, shaft speed (RPM), and thermal buildup.
2. **Zero Closed-Loop Feedback**: The PC calculated a theoretical DAC value and transmitted `SET:<dac_raw>`. The PC ignored load cell readings when commanding the brake, operating entirely blind to actual load.
3. **Protocol Incompatibility with Phase 2 Firmware**: In `arduino/dyno_controller/dyno_controller.ino`, the firmware has been upgraded to run an internal 50 Hz PID loop (lines 87–129). The Arduino sketch no longer processes `SET:<raw>`; instead, line 204 explicitly parses `<SET_TORQUE:torque_nm>`:
   ```c
   // arduino/dyno_controller/dyno_controller.ino lines 204-210
   else if (cmd.startsWith("<SET_TORQUE:")) {
     int startIdx = cmd.indexOf(':') + 1;
     int endIdx = cmd.indexOf('>', startIdx);
     targetTorque = cmd.substring(startIdx, endIdx).toFloat();
     Serial.print("ACK:SET_TORQUE:");
     Serial.println(targetTorque);
   }
   ```

### 2.2 Closed-Loop Replacement Strategy
1. **Eliminate Open-Loop Math**: Remove lines 216–222 entirely from `_on_tick`. The PC will never compute a DAC value.
2. **Transmit Setpoint via Protocol**: When advancing to a profile setpoint (or on run start), transmit the closed-loop command:
   ```python
   self._worker.send_command(f"<SET_TORQUE:{target_torque:.2f}>")
   ```
3. **Firmware Responsibility**: The Arduino hardware PID loop regulates `mcp4725_write(dacValue)` at 50 Hz to minimize the error `targetTorque - currentTorque`.
4. **Telemetry Ingestion**: The Arduino sends the actual resulting DAC value in its 20 Hz `<DATA:torque,speed,dac>` packet, which the PC records as authentic telemetry.

---

## 3. Requirement 2: Stability Monitor & Rolling Buffer Design

### 3.1 Module Placement & Architectural Separation
Per `PROJECT.md` guidelines, backend processing logic belongs in `modules/`, while `gui/` remains focused on user interaction. We propose creating `modules/stability_monitor.py`. This ensures:
- **Decoupled Business Logic**: Zero Qt/GUI dependencies.
- **High-Performance Headless Unit Testing**: Can be rigorously tested in milliseconds using standard Python `unittest`.
- **Clean Interface Contract**: Adheres precisely to `PROJECT.md` Section 4.3.

### 3.2 Evaluation Mathematics & Rolling Buffer Mechanics

#### The Steady-State Condition
The prompt and `PROJECT.md` specify:
> *"Physical measured torque must stay within ±tolerance% of the target setpoint continuously for the full settling time (e.g., 1.5s)."*

Let $T_{\text{target}}$ be the commanded setpoint, $\tau_{\text{tol}}$ be the user-specified tolerance percentage (default: $2.0\%$), and $T_{\text{settle}}$ be the required settling duration (default: $1.5\text{ s}$).

1. **Tolerance Band Calculation**:
   $$\Delta_{\text{band}} = \max\left(|T_{\text{target}}| \times \frac{\tau_{\text{tol}}}{100.0},\ \Delta_{\text{min}}\right)$$
   *Crucial Engineering Edge Case*: If $T_{\text{target}} = 0.0\text{ N}\cdot\text{m}$ (common at the start and end of profiles), $\pm 2\%$ of 0 is 0. Without an absolute lower bound $\Delta_{\text{min}}$ (e.g., $0.1\text{ N}\cdot\text{m}$), analog sensor noise would prevent stability from ever being declared at zero torque.
   Therefore, the valid settling interval is:
   $$I_{\text{stable}} = [T_{\text{target}} - \Delta_{\text{band}},\ T_{\text{target}} + \Delta_{\text{band}}]$$

2. **Rolling Buffer Architecture (`collections.deque`)**:
   - As `<DATA:torque,speed,dac>` telemetry arrives from the Arduino at 20 Hz, `add_reading(torque, timestamp)` appends `(timestamp, torque)` to a bounded FIFO `deque`.
   - Old samples older than $\max(3 \times T_{\text{settle}}, 5.0\text{ s})$ are automatically pruned to maintain minimal memory footprint ($O(1)$ amortized).

3. **Windowed Steady-State Check (`is_stable`)**:
   Given current time $t_{\text{now}}$ and latest reading $(t_{\text{latest}}, y_{\text{latest}})$:
   - **Liveness Gate**: If $t_{\text{now}} - t_{\text{latest}} > t_{\text{stale}}$ (e.g. $0.5\text{ s}$), telemetry has stopped. Return `False`.
   - **Duration Gate**: The buffer must span at least $T_{\text{settle}}$ since the last reset or setpoint change:
     $$(t_{\text{latest}} - t_{\text{oldest}}) \ge T_{\text{settle}}$$
     If elapsed observation time is less than $T_{\text{settle}}$, return `False`.
   - **Continuous Tolerance Gate**: Inspect all readings $(t_i, y_i)$ within the window $[t_{\text{latest}} - T_{\text{settle}}, t_{\text{latest}}]$.
     If **any** reading $y_i \notin I_{\text{stable}}$, return `False`.
     If **all** readings in the settling window fall within $I_{\text{stable}}$, return `True`.

4. **Reset Semantics (`reset`)**:
   - Whenever the dyno steps to a new target setpoint or the session is reset, `StabilityMonitor.reset()` is invoked.
   - This purges the buffer and resets settling timers, ensuring historical samples from prior setpoints cannot falsely satisfy the new setpoint's stability condition.

### 3.3 Proposed Implementation: `modules/stability_monitor.py`

```python
"""
Stability Monitor module.

Monitors physical torque telemetry from the dynamometer test bench to detect
when the system has achieved steady state at a target torque setpoint.
"""

from collections import deque
import time
from typing import Deque, Tuple


class StabilityMonitor:
    """
    Evaluates whether measured torque has settled at a target setpoint.

    Criteria:
      Physical measured torque must stay continuously within ±tolerance%
      of the target setpoint for at least settling_time_s seconds.
    """

    def __init__(
        self,
        tolerance_pct: float = 2.0,
        settling_time_s: float = 1.5,
        min_abs_tolerance: float = 0.1,
        max_staleness_s: float = 0.5,
    ) -> None:
        self._tolerance_pct = float(tolerance_pct)
        self._settling_time_s = float(settling_time_s)
        self._min_abs_tolerance = float(min_abs_tolerance)
        self._max_staleness_s = float(max_staleness_s)

        self._readings: Deque[Tuple[float, float]] = deque()

    @property
    def tolerance_pct(self) -> float:
        return self._tolerance_pct

    @property
    def settling_time_s(self) -> float:
        return self._settling_time_s

    def set_parameters(
        self,
        tolerance_pct: float | None = None,
        settling_time_s: float | None = None,
        min_abs_tolerance: float | None = None,
    ) -> None:
        """Update stability thresholds dynamically."""
        if tolerance_pct is not None:
            if tolerance_pct <= 0:
                raise ValueError("tolerance_pct must be positive")
            self._tolerance_pct = float(tolerance_pct)
        if settling_time_s is not None:
            if settling_time_s <= 0:
                raise ValueError("settling_time_s must be positive")
            self._settling_time_s = float(settling_time_s)
        if min_abs_tolerance is not None:
            self._min_abs_tolerance = float(min_abs_tolerance)

    def add_reading(self, torque: float, timestamp: float | None = None) -> None:
        """
        Record a measured torque reading.

        Parameters
        ----------
        torque : float
            Physical measured torque in N·m.
        timestamp : float | None
            Timestamp in seconds. Defaults to time.perf_counter().
        """
        if timestamp is None:
            timestamp = time.perf_counter()

        self._readings.append((timestamp, float(torque)))

        # Prune readings older than 3x settling time or at least 5 seconds
        prune_cutoff = timestamp - max(self._settling_time_s * 3.0, 5.0)
        while self._readings and self._readings[0][0] < prune_cutoff:
            self._readings.popleft()

    def is_stable(self, target_torque: float, current_time: float | None = None) -> bool:
        """
        Evaluate if measured torque has settled at target_torque.

        Returns True if and only if:
        1. Telemetry is not empty and not stale.
        2. Readings in the buffer span at least settling_time_s.
        3. All readings in the window [t_latest - settling_time_s, t_latest]
           are within [target_torque - tolerance, target_torque + tolerance].
        """
        if not self._readings:
            return False

        latest_time, _ = self._readings[-1]
        now = current_time if current_time is not None else time.perf_counter()

        # Check telemetry staleness
        if (now - latest_time) > self._max_staleness_s:
            return False

        # Check total time span in buffer
        oldest_time, _ = self._readings[0]
        if (latest_time - oldest_time) < self._settling_time_s:
            return False

        # Calculate tolerance band
        band = max(abs(target_torque) * (self._tolerance_pct / 100.0), self._min_abs_tolerance)
        lower_bound = target_torque - band
        upper_bound = target_torque + band

        # Inspect window [latest_time - settling_time_s, latest_time]
        window_start = latest_time - self._settling_time_s
        for t, val in reversed(self._readings):
            if t < window_start:
                break
            if not (lower_bound <= val <= upper_bound):
                return False

        return True

    def reset(self) -> None:
        """Clear reading history when stepping to a new setpoint."""
        self._readings.clear()
```

---

## 4. Requirement 3: Profile Stepping & Execution Model

### 4.1 The Fundamental Architectural Contradiction
In Phase 1, `_on_tick` operated as:
```python
elapsed = self._session.elapsed_seconds()
if elapsed > self._plf.duration:
    self._on_stop()
torque_nm = self._plf.torque_at(elapsed)
```
In this model, `elapsed` marched forward with wall-clock time (`time.perf_counter() - start_time`), and `self._plf.torque_at(elapsed)` performed continuous linear interpolation between CSV rows.

#### The Mathematical Conflict:
If setpoint torque $T(t)$ changes continuously on every tick during a ramp:
- Target torque at $t=1.0\text{ s}$ is $1.0\text{ N}\cdot\text{m}$.
- Target torque at $t=2.5\text{ s}$ is $2.5\text{ N}\cdot\text{m}$.
- Over a $1.5\text{ s}$ settling window, the setpoint changes by $1.5\text{ N}\cdot\text{m}$.
- If tolerance is $\pm 2\%$ of $2.5\text{ N}\cdot\text{m} = \pm 0.05\text{ N}\cdot\text{m}$, the moving target has shifted by $30\times$ the tolerance band!
- **Result**: A steady-state stability detector evaluating continuous linear interpolation will **never** declare stability during a ramp, permanently deadlocking the profile if advancement is gated on stability.

### 4.2 The Solution: Discrete Waypoint Step-and-Hold Model
Dynamometer torque mapping protocols are standardly configured as **Step Profiles**:
- The CSV file `assets/example_profile.csv` contains discrete waypoints:
  ```csv
  time_s,torque_nm
  0.0,0.0
  5.0,5.0
  10.0,10.0
  20.0,20.0
  30.0,30.0
  40.0,25.0
  50.0,15.0
  60.0,0.0
  ```
- Each row defines a target torque setpoint: $\tau_0 = 0.0, \tau_1 = 5.0, \tau_2 = 10.0, \dots$
- **Progression State Machine**:
  1. Setpoint $i$ is commanded to Arduino: `<SET_TORQUE:\tau_i>`.
  2. `StabilityMonitor.reset()` is called. Status is `WAITING`.
  3. Control loop enters `WAITING_STABILITY` state at target $\tau_i$.
  4. Once `StabilityMonitor.is_stable(\tau_i)` evaluates `True`:
     - Status badge updates to `STABLE`.
     - Control loop advances to step $i+1$.
     - If $i+1 \ge N$, all profile setpoints have been executed $\to$ run completes and calls `_on_stop()`.
  5. **Time Representation**: Wall-clock elapsed time continues to accumulate via `DynoSession.elapsed_seconds()`. Thus, the recorded CSV and live graphs accurately display the physical response curve: rise time, transient oscillations, steady-state plateau, and step transitions.

### 4.3 Safety Step Timeout
In physical testing, a motor might stall or the PID loop might oscillate without ever settling within $\pm 2\%$. Without a timeout, the test bench would hold maximum brake torque forever, potentially damaging equipment.
We introduce a configurable `step_timeout_s` (e.g., $30.0\text{ s}$). If stability is not achieved within `step_timeout_s`:
- The bench logs an error or warning.
- For safety, it safely aborts the run (`_on_stop()`) or flags the step as un-settled and advances, alerting the operator.

### 4.4 Flowchart of Closed-Loop Stepping in `MainWindow`

```
 [START RUN]
      │
      ▼
 Step = 0, Target = PLF.torques[0]
 Send "<SET_TORQUE:Target>" to Arduino
 Reset StabilityMonitor
 Set PID Tab Status = WAITING
 Start QTimer (100ms)
      │
      ▼
 ┌─────────────► [_on_data_received] (20 Hz from Arduino)
 │                    │
 │                    ├─ Update _last_torque, _last_speed, _last_dac
 │                    ├─ stability_monitor.add_reading(torque)
 │                    └─ pid_tab.set_stability_status(stability_monitor.is_stable(target))
 │
 └─────────────► [_on_tick] (10 Hz QTimer)
                      │
                      ├─ Check timeout: (step_elapsed > step_timeout) ──► Stop / Alert
                      │
                      ├─ is_stable = stability_monitor.is_stable(target)
                      │
                      ├─ IF is_stable:
                      │      IF Step + 1 < Total_Steps:
                      │           Step += 1
                      │           Target = PLF.torques[Step]
                      │           Send "<SET_TORQUE:Target>"
                      │           stability_monitor.reset()
                      │           pid_tab.set_stability_status(False)
                      │      ELSE:
                      │           _on_stop() [Profile Completed]
                      │
                      ├─ sample = Sample(elapsed, _last_torque, _last_rpm, _last_dac, _last_adc)
                      ├─ session.append_sample(sample)
                      ├─ logger.write(sample)
                      ├─ ctrl.update_live(...)
                      └─ plots.update_samples(...)
```

---

## 5. Requirement 4: Telemetry Data Flow & Authentic Logging

### 5.1 Telemetry Pipeline Breakdown
The telemetry flow across all application tiers is modernized as follows:

| Stage | Component | Phase 1 (Legacy) | Phase 2 (Authentic Closed-Loop) |
|---|---|---|---|
| **Firmware Output** | `dyno_controller.ino` | `SPEED:<adc>` | `<DATA:torque,speed,dac>` at 20 Hz |
| **Serial Worker** | `serial_comm.py` | `speed_received(int)` | `data_received(float, float, int)` |
| **Main Window Ingestion** | `main_window.py` | Stored `_last_adc` only | Stores `_last_torque`, `_last_speed`, `_last_dac`, `_last_rpm` |
| **Brake Command** | `main_window.py` | `SET:<open_loop_dac>` | `<SET_TORQUE:target_torque>` |
| **Sample Object** | `data_model.py` | `torque_nm` was theoretical setpoint; `dac_raw` was open-loop calc | `torque_nm` is physical load cell reading; `dac_raw` is real Arduino DAC output |
| **CSV Logger** | `csv_logger.py` | Logged fake setpoint torque and fake DAC | Logs authentic physical torque and authentic DAC |
| **Live Readouts** | `control_panel.py` | Showed theoretical setpoint | Shows authentic physical torque and authentic DAC |
| **Graphs** | `plot_widget.py` | Plotted theoretical torque | Plots authentic physical torque vs time and torque vs RPM |

### 5.2 Enhancements to Data Models
In `modules/data_model.py`:
`Sample` already contains:
```python
@dataclass
class Sample:
    elapsed_s: float
    torque_nm: float
    rpm: float
    dac_raw: int
    adc_raw: int
```
To support setpoint tracking analytics (comparing target vs measured torque) without breaking backwards compatibility:
```python
@dataclass
class Sample:
    elapsed_s: float
    torque_nm: float         # Authentic measured torque (N·m)
    rpm: float               # Authentic RPM
    dac_raw: int             # Authentic MCP4725 DAC output (0-4095)
    adc_raw: int             # Raw speed ADC count (0-1023)
    target_torque_nm: float = 0.0  # Commanded setpoint (N·m)
```
In `modules/csv_logger.py`:
`FIELDNAMES = ["elapsed_s", "torque_nm", "rpm", "dac_raw", "adc_raw"]`
Because `Sample.torque_nm` and `Sample.dac_raw` now hold authentic telemetry, `csv_logger.py` immediately outputs authentic data rows with zero schema breakage. If desired, `"target_torque_nm"` can be appended as an optional 6th column.

---

## 6. Integration Contract: `PidTuningTab` ↔ `MainWindow`

`gui/pid_tuning_tab.py` contains the UI controls for steady-state parameters:
- `self._tolerance_spin`: tolerance in % (default $2.0\%$).
- `self._settling_spin`: settling time in s (default $1.5\text{ s}$).
- `self._status_label`: status badge displaying `STABLE` or `WAITING`.
- `self._update_btn`: "Update Software Parameters" button.

### 6.1 Wiring Plan
1. In `PidTuningTab`:
   - Declare signal: `sig_update_stability_params = pyqtSignal(float, float)`
   - Implement `tolerance() -> float` and `settling_time() -> float` helper getters.
   - Replace the stub in `_on_update_software_params`:
     ```python
     def _on_update_software_params(self) -> None:
         tol = self._tolerance_spin.value()
         settle = self._settling_spin.value()
         self.sig_update_stability_params.emit(tol, settle)
     ```
2. In `MainWindow`:
   - Connect signal in `_build_ui()`:
     ```python
     self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)
     ```
   - Slot implementation:
     ```python
     @pyqtSlot(float, float)
     def _on_update_stability_params(self, tolerance_pct: float, settling_time_s: float) -> None:
         self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
         self._status(f"Stability parameters updated: ±{tolerance_pct:.1f}%, {settling_time_s:.1f} s")
     ```
   - Connect live telemetry to badge:
     Whenever `is_stable(target)` changes, invoke:
     ```python
     self._pid_tab.set_stability_status(is_stable)
     ```

---

## 7. Concrete Implementation Code Proposals

### 7.1 Proposed `MainWindow` Changes in `gui/main_window.py`

```python
# --- Imports added to gui/main_window.py ---
from modules.stability_monitor import StabilityMonitor

# --- In MainWindow.__init__ ---
self._stability_monitor = StabilityMonitor()
self._current_step_idx: int = 0
self._current_target_torque: float = 0.0
self._last_torque: float = 0.0
self._last_speed: float = 0.0
self._last_dac: int = 0
self._step_start_time: float = 0.0
self._step_timeout_s: float = 30.0

# Connect PID tab stability parameters
self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)

# --- Serial slot updates ---
def _start_worker(self) -> None:
    ...
    self._worker.data_received.connect(self._on_data_received) # New Phase 2 signal
    self._worker.speed_received.connect(self._on_speed_received) # Backward-compat
    ...

@pyqtSlot(float, float, int)
def _on_data_received(self, torque: float, speed: float, dac: int) -> None:
    self._last_torque = torque
    self._last_speed = speed
    self._last_dac = dac
    self._last_rpm = speed * self._calibration.rpm_per_count
    self._last_adc = int(speed)

    # Ingest into stability monitor
    self._stability_monitor.add_reading(torque, time.perf_counter())

    # Live update stability badge
    if self._session.state == RunState.RUNNING:
        stable = self._stability_monitor.is_stable(self._current_target_torque)
        self._pid_tab.set_stability_status(stable)

# --- Run Start updates ---
@pyqtSlot()
def _on_start(self) -> None:
    if self._session.state == RunState.RUNNING:
        return

    # Check PLF
    if not self._plf.is_loaded() or len(self._plf.torques) == 0:
        self._show_error("Cannot Start", "No valid profile loaded.")
        return

    try:
        log_path = self._logger.open(self._calibration.output_dir)
        self._ctrl.set_log_path(log_path)
    except Exception as exc:
        self._show_error("Cannot open log file", str(exc))
        return

    # Initialize stepping & stability monitor
    self._current_step_idx = 0
    self._current_target_torque = float(self._plf.torques[0])
    self._step_start_time = time.perf_counter()
    self._stability_monitor.reset()
    self._pid_tab.set_stability_status(False)

    if self._worker:
        self._worker.send_command("START")
        self._worker.send_command(f"<SET_TORQUE:{self._current_target_torque:.2f}>")

    self._session.start()
    self._timer.start(self._calibration.poll_interval_ms)
    self._status(f"Run started. Setpoint 1/{len(self._plf.torques)}: {self._current_target_torque:.2f} N·m")
    self._update_ui_state()

# --- Replaced _on_tick ---
@pyqtSlot()
def _on_tick(self) -> None:
    if self._session.state != RunState.RUNNING:
        return

    elapsed = self._session.elapsed_seconds()
    now = time.perf_counter()

    # 1. Evaluate stability
    is_stable = self._stability_monitor.is_stable(self._current_target_torque)
    self._pid_tab.set_stability_status(is_stable)

    # 2. Gate profile stepping
    if is_stable:
        next_idx = self._current_step_idx + 1
        if next_idx >= len(self._plf.torques):
            self._status("Profile completed successfully.")
            self._on_stop()
            return
        else:
            self._current_step_idx = next_idx
            self._current_target_torque = float(self._plf.torques[next_idx])
            self._step_start_time = now
            self._stability_monitor.reset()
            self._pid_tab.set_stability_status(False)
            if self._worker:
                self._worker.send_command(f"<SET_TORQUE:{self._current_target_torque:.2f}>")
            self._status(
                f"Stepping to setpoint {next_idx + 1}/{len(self._plf.torques)}: "
                f"{self._current_target_torque:.2f} N·m"
            )
    else:
        # Check safety step timeout
        if (now - self._step_start_time) > self._step_timeout_s:
            self._status(f"Warning: Setpoint {self._current_step_idx + 1} timed out waiting for stability.")
            # Advance or abort depending on safety policy; here advance to prevent stall:
            next_idx = self._current_step_idx + 1
            if next_idx >= len(self._plf.torques):
                self._on_stop()
                return
            self._current_step_idx = next_idx
            self._current_target_torque = float(self._plf.torques[next_idx])
            self._step_start_time = now
            self._stability_monitor.reset()
            if self._worker:
                self._worker.send_command(f"<SET_TORQUE:{self._current_target_torque:.2f}>")

    # 3. Append authentic sample
    sample = Sample(
        elapsed_s=elapsed,
        torque_nm=self._last_torque, # Authentic measured torque
        rpm=self._last_rpm,          # Authentic speed
        dac_raw=self._last_dac,      # Authentic DAC output
        adc_raw=self._last_adc,      # Speed ADC count
        target_torque_nm=self._current_target_torque,
    )
    self._session.append_sample(sample)

    try:
        self._logger.write(sample)
    except Exception:
        pass

    # 4. Live UI updates
    self._ctrl.update_live(
        elapsed,
        self._last_torque,
        self._last_rpm,
        self._last_dac,
        self._session.sample_count(),
    )

    # 5. Plot updates
    if self._session.sample_count() % PLOT_REFRESH_EVERY == 0:
        self._plots.update_samples(self._session.get_snapshot())
```

---

## 8. Testing & Verification Strategy

### 8.1 Unit Testing: `tests/test_stability_monitor.py`
We define a dedicated test suite using `unittest` covering all edge cases:

1. **`test_empty_buffer_not_stable`**: Newly initialized monitor returns `False`.
2. **`test_insufficient_time_not_stable`**: All readings within $\pm 2\%$ of target, but total duration is $1.0\text{ s} < 1.5\text{ s}$. Returns `False`.
3. **`test_stable_after_full_settling_time`**: Readings within tolerance spanning $\ge 1.5\text{ s}$. Returns `True`.
4. **`test_transient_spike_breaks_streak`**: Stable readings for $1.4\text{ s}$, then single out-of-tolerance spike at $1.45\text{ s}$. Returns `False`.
5. **`test_zero_torque_setpoint_handling`**: At $0.0\text{ N}\cdot\text{m}$, verifies `min_abs_tolerance` enables stability detection without divide-by-zero or zero-width band.
6. **`test_stale_telemetry_detection`**: Stable readings present, but last sample is $> 0.5\text{ s}$ old. Returns `False`.
7. **`test_reset_clears_buffer`**: After reaching stable state, `reset()` immediately causes `is_stable()` to return `False`.
8. **`test_parameter_update`**: Changing tolerance from $2\%$ to $10\%$ enables stability on noisy signals that failed under $2\%$.

### 8.2 Integration Testing: `tests/test_closed_loop_stepping.py`
Using headless PyQt6 (`QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest`):

1. **Mock Serial Worker**:
   - Implements `send_command(cmd)` recording outgoing commands.
   - Emits `data_received(torque, speed, dac)` signals on demand.
2. **Profile Stepping Verification**:
   - Load sample PLF with waypoints `[5.0, 10.0, 15.0]`.
   - Start run: verify `<SET_TORQUE:5.00>` is transmitted.
   - Tick timer while emitting torque = $2.0\text{ N}\cdot\text{m}$ (error $= 3.0\text{ N}\cdot\text{m}$). Verify step index remains at 0 over 20 ticks.
   - Emit torque = $5.02\text{ N}\cdot\text{m}$ continuously for $1.6\text{ s}$.
   - Tick timer: verify step index advances to 1 and outgoing command `<SET_TORQUE:10.00>` is emitted!
   - Repeat for final step: verify auto-stop is triggered and log file contains authentic telemetry samples.
3. **PID Tab Status Badge Verification**:
   - Verify badge text is `"WAITING"` during transition and turns `"STABLE"` upon achieving steady state.

---

## 9. Conclusion & Recommendations

1. **Clean Separation**: Implement `modules/stability_monitor.py` as an isolated pure-Python class with full test coverage.
2. **Protocol Compliance**: Remove Phase 1 open-loop math lines 216–222 in `gui/main_window.py` and replace with `<SET_TORQUE:t>`.
3. **Profile Stepping Model**: Adopt the discrete waypoint step-and-hold model, which is mathematically sound and aligns with physical dynamometer operation.
4. **Authentic Telemetry**: Ingest `<DATA:t,s,d>` in `_on_data_received` and populate `Sample` with real physical measurements, automatically propagating authentic data to CSV logs and plots.
