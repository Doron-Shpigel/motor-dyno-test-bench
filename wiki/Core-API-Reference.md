# Core API Reference

The `motor-dyno-test-bench` core Python API is entirely headless, containing zero dependencies on PyQt6, GUI toolkits, or display servers. It provides programmatic access to dynamometer sequencing, closed-loop torque control, stability monitoring, calibration wizards, and telemetry logging.

---

## Table of Modules & Classes

| Module | Class | Primary Responsibility |
|---|---|---|
| `modules.engine` | [`DynoEngine`](#1-dynoengine) | Master test bench controller and state orchestrator |
| `modules.transport` | [`BaseTransport`](#2-basetransport) | Abstract communication interface and packet parser |
| `modules.transport` | [`SerialTransport`](#3-serialtransport) | Dedicated background thread for physical USB serial communication |
| `modules.transport` | [`MockTransport`](#4-mocktransport) | In-memory transport for deterministic testing and programmatic assertions |
| `modules.transport` | [`SimulatedTransport`](#5-simulatedtransport) | Realistic physical dynamic model of motor inertia, load droop, and torque settling |
| `modules.stability_monitor` | [`StabilityMonitor`](#6-stabilitymonitor) | Sliding-window tolerance and settling-time evaluation engine |
| `modules.plf` | [`PiecewiseLinearFunction`](#7-piecewiselinearfunction) | Monotonic CSV torque profile loader and linear interpolator |
| `modules.csv_logger` | [`CSVLogger`](#8-csvlogger) | High-speed, buffered CSV telemetry file logger |
| `modules.data_model` | [`DynoSession`](#9-dynosession) | Thread-safe sample accumulator and snapshot provider |
| `modules.data_model` | [`Sample`](#10-sample) | Strongly typed telemetry data point dataclass |
| `modules.calibration` | [`CalibrationSettings`](#11-calibrationsettings) | Hardware conversion factors, timings, and scale configurations |

---

## 1. `DynoEngine`

**Module:** `modules.engine`  
**Purpose:** Orchestrates the dynamometer test bench: manages hardware transports, executes manual and profile test runs, gates profile advancement via `StabilityMonitor`, manages relays, executes torque calibration routines, and records telemetry.

### Constructor
```python
def __init__(
    self,
    transport: BaseTransport | None = None,
    calibration: CalibrationSettings | None = None,
    stability_monitor: StabilityMonitor | None = None,
    control_mode: str = "hybrid",
    step_timeout_s: float = 30.0,
    on_telemetry: Callable[[Sample], None] | None = None,
    on_state_change: Callable[[RunState], None] | None = None,
    on_step: Callable[[int, float], None] | None = None,
    on_stability_change: Callable[[bool], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_pid: Callable[[float, float, float], None] | None = None,
    on_relay: Callable[[str, bool], None] | None = None,
) -> None
```

#### Parameters
- `transport` (`BaseTransport | None`): Hardware or mock transport instance. If `None`, defaults to uninitialized until `connect()` is called (which instantiates a `SerialTransport`).
- `calibration` (`CalibrationSettings | None`): Hardware conversion factors. If `None`, instantiates default settings.
- `stability_monitor` (`StabilityMonitor | None`): Stability monitor instance. If `None`, instantiates default monitor.
- `control_mode` (`str`): Default control mode (`"hybrid"`, `"open_loop"`, or `"closed_loop"`).
- `step_timeout_s` (`float`): Maximum duration in seconds to wait for torque stability before automatically advancing to the next step (default: `30.0`).
- `on_*` (`Callable | None`): Optional single-callback hooks for lifecycle and telemetry events.

---

### Properties

| Property | Type | Description |
|---|---|---|
| `state` | `RunState` | Current run state (`IDLE`, `RUNNING`, `PAUSED`, `FINISHED`, `ERROR`). |
| `mode` | `RunMode` | Current active mode (`NONE`, `PROFILE`, `MANUAL`). |
| `target_torque` | `float` | Commanded setpoint torque in $\text{N}\cdot\text{m}$. |
| `current_torque` | `float` | Latest calibrated measured torque in $\text{N}\cdot\text{m}$. |
| `current_torque_raw` | `float` | Latest raw ADC reading from the torque load cell ($0$–$1023$). |
| `current_rpm` | `float` | Latest measured shaft rotational speed in $\text{RPM}$. |
| `current_dac` | `int` | Commanded 12-bit DAC output value ($0$–$4095$). |
| `current_adc` | `int` | Raw speed ADC reading ($0$–$1023$). |
| `is_stable` | `bool` | True if torque reading is currently settled within tolerance around target. |
| `is_connected` | `bool` | True if the transport is active and connected. |
| `relays` | `dict[str, bool]` | Current state dictionary for `"BRAKE"`, `"SENSOR"`, and `"AUX"` relays. |
| `session` | `DynoSession` | Underlying session accumulating samples. |
| `calibration` | `CalibrationSettings` | Active calibration settings instance. |
| `stability_monitor` | `StabilityMonitor` | Underlying stability monitor instance. |
| `control_mode` | `str` | Active control mode (`"hybrid"`, `"open_loop"`, or `"closed_loop"`). |
| `current_step_idx` | `int` | Zero-based index of the active step in a profile run. |
| `step_timeout_s` | `float` | Timeout in seconds for profile step stability fallback. |
| `stored_pid` | `tuple[float, float, float]` | Latest $(K_p, K_i, K_d)$ gains read from Arduino EEPROM. |

---

### Methods

#### `connect(port: str = "", baud: int = 115200) -> None`
Connects to hardware serial port or initiates transport.
- **Parameters:** `port` (`str`), `baud` (`int`).
- **Raises:** `serial.SerialException` or `OSError` if port cannot be opened.

#### `disconnect() -> None`
Safely stops active test run (if running) and releases transport resources.

#### `start_manual(target_torque: float, mode: str = "hybrid") -> None`
Begins a manual dyno run at the specified target torque.
- **Parameters:** `target_torque` ($\text{N}\cdot\text{m}$), `mode` (`"hybrid"`, `"open_loop"`, `"closed_loop"`).

#### `set_manual_torque(torque: float) -> None`
Dynamically adjusts the target torque during an active manual run.

#### `start_profile(profile: str | Path | PiecewiseLinearFunction, mode: str | None = None) -> None`
Loads a torque-time profile CSV and initiates an automated profile run gated by the stability monitor.
- **Parameters:** `profile` (`str | Path | PiecewiseLinearFunction`).
- **Raises:** `ValueError` if profile contains no points or is invalid; `FileNotFoundError` if path does not exist.

#### `stop() -> None`
Safely terminates an active test run:
1. Emits `STOP` to microcontroller.
2. Zeroes 12-bit DAC output to release brake.
3. Opens all hardware relays (`BRAKE`, `SENSOR`, `AUX`).
4. Closes and flushes CSV logger.
5. Transitions `session.state` to `RunState.FINISHED`.

#### `reset() -> None`
Clears session data, zeroes sensors, and resets engine to `RunState.IDLE`.

#### `set_relay(name: str, state: bool | int) -> None`
Controls hardware relay (`"BRAKE"`, `"SENSOR"`, `"AUX"`).

#### `get_pid() -> None`
Queries active PID gains stored in Arduino EEPROM. Dispatches `on_pid` callback upon receipt.

#### `set_pid(kp: float, ki: float, kd: float) -> None`
Burns new PID tuning gains to Arduino EEPROM.
- **Raises:** `ValueError` if any gain is negative, non-finite, or $>1000.0$.

#### `start_calibration() -> None`
Initiates maximum torque calibration routine: powers sensor relay, applies full DAC command ($4095$), and monitors peak ADC force.

#### `finish_calibration() -> bool`
Completes torque calibration: zeroes DAC, powers down sensor, and computes new `torque_per_count` if peak $\text{ADC} > 512.0$. Returns `True` on success.

#### `tick(now: float | None = None) -> None`
Executes a single deterministic step of the control loop: evaluates stability, checks step timeout fallback, handles hybrid mode transitions, samples telemetry, and writes to CSV.

#### `start_loop(interval_s: float | None = None) -> None`
Starts an autonomous background thread executing `tick()` at the configured interval.

#### `stop_loop() -> None`
Stops the background loop thread.

#### `add_listener(event_name: str, callback: Callable) -> None`
Registers an event listener for multi-subscriber architectures. Supported events: `"on_telemetry"`, `"on_state_change"`, `"on_step"`, `"on_stability_change"`, `"on_status"`, `"on_error"`, `"on_pid"`, `"on_relay"`.

---

### Practical Example: Automated Test Run
```python
import time
from modules.engine import DynoEngine
from modules.transport import SimulatedTransport

# 1. Initialize engine with simulated physics
engine = DynoEngine(transport=SimulatedTransport(), control_mode="hybrid")
engine.connect()

# 2. Subscribe to telemetry
engine.add_listener("on_telemetry", lambda s: print(
    f"[{s.elapsed_s:5.2f}s] Torque: {s.torque_nm:4.2f} N·m (Target: {s.target_torque_nm:4.2f}) | RPM: {s.rpm:6.1f}"
))

# 3. Start automated profile run from CSV
engine.start_profile("assets/example_profile.csv")

# 4. Run autonomous background control loop
engine.start_loop(interval_s=0.05)

# Wait until profile finishes
while engine.state.name == "RUNNING":
    time.sleep(0.5)

engine.stop_loop()
engine.disconnect()
print("Test completed successfully.")
```

---

## 2. `BaseTransport`

**Module:** `modules.transport`  
**Purpose:** Abstract base class defining communication interfaces, inbound packet decoding, and typed outbound helper methods.

### Key Methods
- `connect(port: str | None = None, baudrate: int | None = None) -> None`: Open connection.
- `disconnect() -> None`: Terminate connection.
- `send_command(cmd: str) -> None`: Send raw newline-terminated ASCII string.
- `send_start()`: Send `START`.
- `send_stop()`: Send `STOP`.
- `send_reset()`: Send `RESET`.
- `send_ping()`: Send `PING`.
- `send_get_pid()`: Send `<GET_PID>`.
- `send_set_pid(kp: float, ki: float, kd: float)`: Send `<SET_PID:kp,ki,kd>`.
- `send_set_torque(torque_nm: float)`: Send `<SET_TORQUE:t>`.
- `send_set_dac(dac_val: int | float)`: Send `<SET_DAC:d>`.
- `send_relay(name: str, state: bool | int)`: Send `<RELAY:NAME,STATE>`.
- `parse_line(line: str) -> None`: Decodes incoming packet frames (`<DATA:...>`, `<PID_VALS:...>`, `ACK:...`, `DYNO_READY`, `ERR:...`).

---

## 3. `SerialTransport`

**Module:** `modules.transport`  
**Inherits:** `BaseTransport`  
**Purpose:** Robust serial port transport executing in a dedicated background `threading.Thread`. Uses a thread-safe `queue.Queue` for outbound transmissions and handles Arduino bootloader reset delays.

### Constructor
```python
def __init__(
    self,
    port: str = "",
    baudrate: int = 115200,
    boot_delay: float = 2.0,
    serial_factory: Any = serial.Serial,
    read_timeout: float = 0.05,
    write_timeout: float = 1.0,
    **callbacks
) -> None
```

#### Features
- **Non-blocking command queuing**: Calls to `send_command()` place items in `queue.Queue` and return immediately.
- **Automatic DTR reset stabilization**: Waits `boot_delay` (default $2.0\text{ s}$) upon opening serial connection to permit Arduino bootloader initialization.
- **Graceful disconnection**: Flushes `RESET\n` and closes port cleanly upon `disconnect()`.

---

## 4. `MockTransport`

**Module:** `modules.transport`  
**Inherits:** `BaseTransport`  
**Purpose:** In-memory synchronous transport for automated testing, CI pipelines, and unit verification.

### Test Simulation Methods
- `simulate_data(torque: float, speed_rpm: float, dac_raw: int) -> None`: Fires `on_data` callback.
- `simulate_pid(kp: float, ki: float, kd: float) -> None`: Fires `on_pid` callback.
- `simulate_ack(cmd: str) -> None`: Fires `on_ack` callback.
- `simulate_ready() -> None`: Fires `on_ready` callback.
- `simulate_error(msg: str) -> None`: Fires `on_error` callback.
- `simulate_raw_line(line: str) -> None`: Feeds a raw string through `parse_line()`.

---

## 5. `SimulatedTransport`

**Module:** `modules.transport`  
**Inherits:** `MockTransport`  
**Purpose:** Autonomous simulated hardware transport running a dynamic motor physics engine in a background thread. Enables full GUI/TUI evaluation without physical hardware.

### Simulation Physics Model
- **Motor Spinup & Speed Sag**:
  $$\text{RPM}_{\text{goal}} = \max(400.0, \text{TargetRPM} - (\tau_{\text{load}} \times 100.0))$$
- **Closed-Loop Torque Tracking**: Simulates realistic mechanical rise-time and settling dynamics with low-amplitude Gaussian measurement noise ($\pm 0.008\text{ N}\cdot\text{m}$).
- **Automatic Packet Handling**: Automatically responds to `PING`, `<GET_PID>`, `<SET_PID>`, and relay toggles.

---

## 6. `StabilityMonitor`

**Module:** `modules.stability_monitor`  
**Purpose:** Sliding-window steady-state detector ensuring the physical system has settled at a target torque setpoint before advancing automated profile sequences.

### Constructor
```python
def __init__(
    self,
    tolerance_pct: float = 2.0,
    settling_time_s: float = 1.5,
    min_abs_tolerance: float = 0.1,
    max_staleness_s: float = 0.5,
) -> None
```

### Methods
- `add_reading(torque: float, timestamp: float | None = None) -> None`: Ingests a torque measurement. Automatically prunes historical samples older than $3 \times \text{settling\_time\_s}$.
- `is_stable(target_torque: float, current_time: float | None = None) -> bool`: Evaluates stability criteria:
  1. Buffer contains samples and latest reading is not stale ($< \text{max\_staleness\_s}$).
  2. Samples in buffer span at least `settling_time_s`.
  3. All readings within the settling window fall strictly within:
     $$\Delta_{\text{tol}} = \max\left(|T_{\text{target}}| \times \frac{\text{tolerance\_pct}}{100}, \text{min\_abs\_tolerance}\right)$$
     $$[T_{\text{target}} - \Delta_{\text{tol}}, T_{\text{target}} + \Delta_{\text{tol}}]$$
- `reset() -> None`: Clears all history.

---

## 7. `PiecewiseLinearFunction`

**Module:** `modules.plf`  
**Purpose:** Loads a two-column CSV profile (`time_s`, `torque_nm`) and performs linear interpolation.

### Methods
- `load_csv(filepath: str | Path) -> None`: Parses CSV file. Validates that `time_s` values are strictly monotonically increasing ($t_{i+1} > t_i$).
  - **Raises:** `PLFError` if file is missing required columns, contains non-numeric data, or is non-monotonic; `FileNotFoundError` if missing.
- `torque_at(time_s: float) -> float`: Evaluates linear interpolation. Clamps to first/last value for queries outside $[0, \text{duration}]$.
- `summary() -> str`: Returns human-readable profile metadata string.

---

## 8. `CSVLogger`

**Module:** `modules.csv_logger`  
**Purpose:** Thread-safe, auto-timestamped CSV telemetry logger.

### Output Format
```csv
elapsed_s,torque_nm,rpm,dac_raw,adc_raw
0.0500,0.0120,2810.50,0,513
0.1000,0.5240,2790.20,410,565
```

### Methods
- `open_temp() -> Path`: Opens `temp_run.csv` in the local working directory.
- `save_to(dest_dir: str | Path, timestamp: str) -> Path | None`: Moves the temporary log to `dest_dir/dyno_log_{timestamp}.csv`.
- `open_explicit(filepath: str | Path) -> Path`: Opens an explicit file destination.
- `write(sample: Sample) -> None`: Formats and flushes a `Sample` dataclass row to disk.
- `close() -> None`: Flushes buffers and closes file descriptor. Supports context manager protocol (`with CSVLogger() as logger:`).

---

## 9. `DynoSession`

**Module:** `modules.data_model`  
**Purpose:** Thread-safe data model accumulating telemetry points for an active run.

### Methods
- `start(mode: RunMode) -> None`: Clears samples, records start timestamp, sets state to `RunState.RUNNING`.
- `finish() -> None`: Sets state to `RunState.FINISHED`.
- `reset() -> None`: Clears all samples and returns state to `RunState.IDLE`.
- `append_sample(sample: Sample) -> None`: Atomically appends sample under thread lock.
- `get_snapshot() -> list[Sample]`: Returns a thread-safe shallow copy of the sample buffer.
- `elapsed_seconds() -> float`: Returns duration since run started.

---

## 10. `Sample`

**Module:** `modules.data_model`  
**Purpose:** Dataclass representing a discrete telemetry sample.

```python
@dataclass
class Sample:
    elapsed_s: float              # Seconds since test run started
    torque_nm: float              # Calibrated measured torque (N·m)
    rpm: float                    # Calibrated shaft rotational speed (RPM)
    dac_raw: int                  # Commanded 12-bit DAC code (0-4095)
    adc_raw: int                  # Raw ADC speed sensor counts (0-1023)
    target_torque_nm: float = 0.0 # Active commanded torque setpoint (N·m)
```

---

## 11. `CalibrationSettings`

**Module:** `modules.calibration`  
**Purpose:** Plain-data configuration container for hardware conversion factors and app settings.

```python
@dataclass
class CalibrationSettings:
    max_torque_nm: float = 5.0                          # N·m corresponding to DAC=4095
    rpm_per_count: float = 0.5                          # RPM = adc_raw * rpm_per_count
    poll_interval_ms: int = 100                         # Control-loop tick interval in ms
    output_dir: str = field(default_factory=...)        # Default output directory for CSV logs
    torque_per_count: float = 5.0 / (1023.0 - 512.0)    # Conversion factor from ADC counts to N·m
```
