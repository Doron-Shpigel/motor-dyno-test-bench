"""
Dyno Core Engine module.

Pure Python, headless Core API for dynamometer control, stability gating,
profile sequencing, calibration, relay handling, and PID logic.
Decoupled entirely from PyQt6 / GUI frameworks.
"""

from collections import defaultdict
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable

from modules.calibration import CalibrationSettings
from modules.csv_logger import CSVLogger
from modules.data_model import DynoSession, RunMode, RunState, Sample
from modules.plf import PiecewiseLinearFunction
from modules.stability_monitor import StabilityMonitor
from modules.transport import (
    BaseTransport,
    MockTransport,
    SerialTransport,
    list_serial_ports,
)


class DynoEngine:
    """
    Headless Dynamometer Core Controller.

    Orchestrates the complete test bench workflow:
      - Connection management via pure Python transports.
      - Hybrid, open-loop, and closed-loop control modes.
      - Manual and profile runs with stability gating & timeout fallback.
      - Hardware relay handling with emergency/stop shutoff.
      - Torque sensor calibration.
      - Integrated CSV logging.
      - Event hooks / callbacks for full telemetry and lifecycle observability.
      - Deterministic tick() or autonomous background loop.
    """

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
    ) -> None:
        self._lock = threading.RLock()

        # Core components
        self._calibration = calibration if calibration is not None else CalibrationSettings()
        self._stability_monitor = stability_monitor if stability_monitor is not None else StabilityMonitor()
        self._session = DynoSession()
        self._logger = CSVLogger()
        self._plf = PiecewiseLinearFunction()

        # Transport & connection
        self._transport: BaseTransport | None = None
        if transport is not None:
            self.set_transport(transport)

        # Control configuration
        self._control_mode = "hybrid"
        self.control_mode = control_mode
        self._step_timeout_s = float(step_timeout_s)
        self._pid_active = False

        # Live telemetry & state
        self._target_torque = 0.0
        self._current_torque = 0.0
        self._current_torque_raw = 0.0
        self._current_rpm = 0.0
        self._current_dac = 0
        self._current_adc = 0
        self._current_step_idx = 0
        self._step_start_time = 0.0
        self._prev_stable = False
        self._stored_pid: tuple[float, float, float] = (100.0, 10.0, 1.0)

        # Hardware Relays
        self._relays: dict[str, bool] = {
            "BRAKE": False,
            "SENSOR": False,
            "AUX": False,
        }

        # Calibration state
        self._is_calibrating = False
        self._max_calib_reading = 0.0

        # Background loop
        self._loop_thread: threading.Thread | None = None
        self._loop_running = False
        self._loop_stop_event = threading.Event()

        # Event hooks (single callback attributes)
        self.on_telemetry = on_telemetry
        self.on_state_change = on_state_change
        self.on_step = on_step
        self.on_stability_change = on_stability_change
        self.on_status = on_status
        self.on_error = on_error
        self.on_pid = on_pid
        self.on_relay = on_relay

        # Multi-listener registry
        self._listeners: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> RunState:
        """Current lifecycle run state (IDLE, RUNNING, PAUSED, FINISHED, ERROR)."""
        return self._session.state

    @property
    def mode(self) -> RunMode:
        """Current run mode (NONE, PROFILE, MANUAL)."""
        return self._session.run_mode

    @property
    def target_torque(self) -> float:
        """Target setpoint torque in N·m."""
        return self._target_torque

    @property
    def current_torque(self) -> float:
        """Latest measured torque in N·m."""
        return self._current_torque

    @property
    def current_torque_raw(self) -> float:
        """Raw ADC reading from torque sensor."""
        return self._current_torque_raw

    @property
    def current_rpm(self) -> float:
        """Latest measured shaft speed in RPM."""
        return self._current_rpm

    @property
    def current_dac(self) -> int:
        """Latest commanded 12-bit DAC output (0-4095)."""
        return self._current_dac

    @property
    def current_adc(self) -> int:
        """Latest raw speed ADC count."""
        return self._current_adc

    @property
    def is_stable(self) -> bool:
        """True if torque reading is settled within tolerance around setpoint."""
        return self._stability_monitor.is_stable(self._target_torque)

    @property
    def is_connected(self) -> bool:
        """True if transport is active and connected."""
        return self._transport is not None and self._transport.is_connected

    @property
    def relays(self) -> dict[str, bool]:
        """Dictionary of hardware relay states (BRAKE, SENSOR, AUX)."""
        with self._lock:
            return dict(self._relays)

    @property
    def session(self) -> DynoSession:
        """Underlying DynoSession accumulating data samples."""
        return self._session

    @property
    def calibration(self) -> CalibrationSettings:
        """Calibration settings and hardware conversion factors."""
        return self._calibration

    @calibration.setter
    def calibration(self, val: CalibrationSettings) -> None:
        with self._lock:
            self._calibration = val

    @property
    def stability_monitor(self) -> StabilityMonitor:
        """Underlying StabilityMonitor instance."""
        return self._stability_monitor

    @property
    def control_mode(self) -> str:
        """Active control mode ('hybrid', 'open_loop', or 'closed_loop')."""
        return self._control_mode

    @control_mode.setter
    def control_mode(self, val: str) -> None:
        clean = str(val).lower().strip()
        if clean not in ("hybrid", "open_loop", "closed_loop"):
            raise ValueError(
                f"Invalid control mode '{val}'. Must be 'hybrid', 'open_loop', or 'closed_loop'."
            )
        with self._lock:
            self._control_mode = clean
            if self._session.state == RunState.RUNNING and self._session.run_mode == RunMode.MANUAL:
                self._command_torque_setpoint(self._target_torque)

    @property
    def current_step_idx(self) -> int:
        """Index of the currently active step in a profile run."""
        return self._current_step_idx

    @property
    def step_timeout_s(self) -> float:
        """Timeout in seconds for profile step stability fallback."""
        return self._step_timeout_s

    @step_timeout_s.setter
    def step_timeout_s(self, val: float) -> None:
        if not math.isfinite(val) or val <= 0:
            raise ValueError("step_timeout_s must be positive and finite")
        self._step_timeout_s = float(val)

    @property
    def transport(self) -> BaseTransport | None:
        """Current transport instance."""
        return self._transport

    @property
    def stored_pid(self) -> tuple[float, float, float]:
        """Latest PID values read from Arduino EEPROM."""
        return self._stored_pid

    # ------------------------------------------------------------------
    # Multi-listener event management
    # ------------------------------------------------------------------

    def add_listener(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Register an event callback listener."""
        with self._lock:
            self._listeners[event_name].append(callback)

    def remove_listener(self, event_name: str, callback: Callable[..., Any]) -> None:
        """Remove an event callback listener."""
        with self._lock:
            if callback in self._listeners[event_name]:
                self._listeners[event_name].remove(callback)

    def _notify(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Safely dispatch event to registered callback and listeners."""
        single_cb = getattr(self, event_name, None)
        if single_cb is not None and callable(single_cb):
            try:
                single_cb(*args, **kwargs)
            except Exception as exc:
                if event_name != "on_error":
                    self._notify("on_error", f"Error in {event_name} callback: {exc}")

        listeners = list(self._listeners.get(event_name, []))
        for listener in listeners:
            try:
                listener(*args, **kwargs)
            except Exception as exc:
                if event_name != "on_error":
                    self._notify("on_error", f"Error in {event_name} listener: {exc}")

    # ------------------------------------------------------------------
    # Connection Management
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> list[str]:
        """Return available serial ports."""
        return list_serial_ports()

    def set_transport(self, transport: BaseTransport) -> None:
        """Attach a transport and hook callbacks."""
        with self._lock:
            if self._transport is not None and self._transport.is_connected:
                self._transport.disconnect()

            self._transport = transport
            transport.on_data = self._handle_transport_data
            transport.on_pid = self._handle_transport_pid
            transport.on_ack = self._handle_transport_ack
            transport.on_ready = self._handle_transport_ready
            transport.on_error = self._handle_transport_error
            transport.on_connected = self._handle_transport_connected
            transport.on_disconnected = self._handle_transport_disconnected

    def connect(self, port: str = "", baud: int = 115200) -> None:
        """Connect to hardware serial or start transport."""
        with self._lock:
            if self._transport is None:
                self.set_transport(SerialTransport(port=port, baudrate=baud))
            self._transport.connect(port=port, baudrate=baud)

    def disconnect(self) -> None:
        """Disconnect transport and stop active run if needed."""
        with self._lock:
            if self._session.state == RunState.RUNNING:
                self.stop()
            if self._transport is not None:
                self._transport.disconnect()

    # ------------------------------------------------------------------
    # Transport Event Handlers
    # ------------------------------------------------------------------

    def _handle_transport_connected(self) -> None:
        self._notify("on_status", "Transport connected.")

    def _handle_transport_disconnected(self) -> None:
        with self._lock:
            if self._session.state == RunState.RUNNING:
                self.stop()
        self._notify("on_status", "Transport disconnected.")

    def _handle_transport_ready(self) -> None:
        self._notify("on_status", "Arduino ready. Querying PID parameters...")
        self.get_pid()

    def _handle_transport_ack(self, cmd: str) -> None:
        self._notify("on_status", f"ACK: {cmd}")

    def _handle_transport_error(self, msg: str) -> None:
        self._notify("on_error", msg)

    def _handle_transport_pid(self, kp: float, ki: float, kd: float) -> None:
        with self._lock:
            self._stored_pid = (kp, ki, kd)
        self._notify("on_pid", kp, ki, kd)
        self._notify("on_status", f"PID updated: Kp={kp:.4f}, Ki={ki:.4f}, Kd={kd:.4f}")

    def _handle_transport_data(self, torque_adc: float, speed_adc: float, dac_val: int) -> None:
        with self._lock:
            self._current_torque_raw = torque_adc
            self._current_torque = (torque_adc - 512.0) * self._calibration.torque_per_count
            self._current_rpm = speed_adc * self._calibration.rpm_per_count
            self._current_dac = dac_val
            self._current_adc = int(speed_adc)

            # Max Torque Calibration peak monitoring
            if self._is_calibrating:
                self._max_calib_reading = max(self._max_calib_reading, self._current_torque_raw)
                if self._current_rpm > 1.0:
                    self.finish_calibration()

            # Stability ingestion
            self._stability_monitor.add_reading(self._current_torque, time.perf_counter())

            # Immediate stability check
            if self._session.state == RunState.RUNNING:
                stable = self._stability_monitor.is_stable(self._target_torque)
                if stable != self._prev_stable:
                    self._prev_stable = stable
                    self._notify("on_stability_change", stable)

                # Real-time hybrid transition check
                if self._control_mode == "hybrid":
                    if not self._pid_active and self._current_rpm > 1.0:
                        self._send_set_torque(self._target_torque)
                        self._pid_active = True
                    elif self._pid_active and self._current_rpm <= 1.0:
                        dac = self._calculate_open_loop_dac(self._target_torque)
                        self._send_set_dac(dac)
                        self._pid_active = False

    # ------------------------------------------------------------------
    # Control Mode Helpers & Command Transmission
    # ------------------------------------------------------------------

    def _send_command(self, cmd: str) -> None:
        if self._transport is not None:
            self._transport.send_command(cmd)

    def _send_set_dac(self, dac_val: int | float) -> None:
        if self._transport is not None:
            self._transport.send_set_dac(dac_val)
        else:
            clamped = max(0, min(4095, int(round(float(dac_val)))))
            self._send_command(f"<SET_DAC:{clamped}>")

    def _send_set_torque(self, torque_nm: float) -> None:
        if self._transport is not None:
            self._transport.send_set_torque(torque_nm)
        else:
            self._send_command(f"<SET_TORQUE:{float(torque_nm):.2f}>")

    def _send_relay(self, name: str, state: bool | int) -> None:
        if self._transport is not None:
            self._transport.send_relay(name, state)
        else:
            val = 1 if state else 0
            self._send_command(f"<RELAY:{str(name).upper()},{val}>")

    def _calculate_open_loop_dac(self, torque: float) -> int:
        """Map torque setpoint to 12-bit DAC value using calibrated max torque."""
        max_t = self._calibration.max_torque_nm if self._calibration.max_torque_nm > 0 else 5.0
        dac = int(round((torque / max_t) * 4095))
        return max(0, min(4095, dac))

    def _command_torque_setpoint(self, torque: float) -> None:
        """Applies configured control logic: open-loop, closed-loop, or hybrid."""
        mode = self._control_mode
        if mode == "open_loop":
            dac = self._calculate_open_loop_dac(torque)
            self._send_set_dac(dac)
            self._pid_active = False
        elif mode == "closed_loop":
            self._send_set_torque(torque)
            self._pid_active = True
        else:  # hybrid
            if self._current_rpm > 1.0:
                self._send_set_torque(torque)
                self._pid_active = True
            else:
                dac = self._calculate_open_loop_dac(torque)
                self._send_set_dac(dac)
                self._pid_active = False

    # ------------------------------------------------------------------
    # Manual Run
    # ------------------------------------------------------------------

    def start_manual(self, target_torque: float, mode: str = "hybrid") -> None:
        """
        Start a manual dyno run at target_torque.
        """
        with self._lock:
            if self._session.state == RunState.RUNNING:
                return

            self.control_mode = mode
            self._target_torque = float(target_torque)

            self._stability_monitor.reset()
            self._prev_stable = False
            self._notify("on_stability_change", False)

            if not self._logger.is_open():
                self.start_logging()

            self._send_command("START")
            self._command_torque_setpoint(self._target_torque)

            self._session.start(RunMode.MANUAL)
            self._notify("on_state_change", RunState.RUNNING)
            self._notify("on_status", f"Manual Run started. Setpoint: {self._target_torque:.2f} N·m")

    def set_manual_torque(self, torque: float) -> None:
        """Update commanded target torque in manual mode."""
        with self._lock:
            self._target_torque = float(torque)
            if self._session.state == RunState.RUNNING and self._session.run_mode == RunMode.MANUAL:
                self._stability_monitor.reset()
                self._prev_stable = False
                self._notify("on_stability_change", False)
                self._command_torque_setpoint(self._target_torque)
                self._notify("on_status", f"Manual torque setpoint updated: {self._target_torque:.2f} N·m")

    # ------------------------------------------------------------------
    # Profile Run
    # ------------------------------------------------------------------

    def start_profile(
        self,
        profile: str | Path | PiecewiseLinearFunction,
        mode: str | None = None,
    ) -> None:
        """
        Start an automated profile run gated by stability monitor.
        """
        with self._lock:
            if self._session.state == RunState.RUNNING:
                return

            if isinstance(profile, (str, Path)):
                plf = PiecewiseLinearFunction()
                plf.load_csv(profile)
                self._plf = plf
            elif isinstance(profile, PiecewiseLinearFunction):
                if not profile.is_loaded() or len(profile.torques) == 0:
                    raise ValueError("Provided PiecewiseLinearFunction is not loaded.")
                self._plf = profile
            else:
                raise TypeError("profile must be a file path (str | Path) or PiecewiseLinearFunction")

            if len(self._plf.torques) == 0:
                raise ValueError("Profile contains no setpoints.")

            if mode is not None:
                self.control_mode = mode

            self._stability_monitor.reset()
            self._prev_stable = False
            self._notify("on_stability_change", False)

            if not self._logger.is_open():
                self.start_logging()

            self._current_step_idx = 0
            self._target_torque = float(self._plf.torques[0])
            self._step_start_time = time.perf_counter()

            self._send_command("START")
            self._command_torque_setpoint(self._target_torque)

            self._session.start(RunMode.PROFILE)
            self._notify("on_state_change", RunState.RUNNING)
            self._notify("on_step", self._current_step_idx, self._target_torque)
            self._notify(
                "on_status",
                f"Profile Run started. Setpoint 1/{len(self._plf.torques)}: {self._target_torque:.2f} N·m",
            )

    # ------------------------------------------------------------------
    # Run Control (stop, reset)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """
        Safely stop the active run:
          - Sends STOP to controller.
          - Zeros the DAC output.
          - Turns off all hardware relays.
          - Closes logging.
          - Updates session state to FINISHED.
        """
        with self._lock:
            self._send_command("STOP")
            self._send_set_dac(0)

            # Safety: turn off all hardware relays
            for relay_name in list(self._relays.keys()):
                self._relays[relay_name] = False
                self._send_relay(relay_name, False)
                self._notify("on_relay", relay_name, False)

            self._session.finish()
            if self._logger.is_open():
                self._logger.close()

            self._stability_monitor.reset()
            self._prev_stable = False
            self._pid_active = False

            self._notify("on_state_change", RunState.FINISHED)
            self._notify("on_status", "Run stopped. Relays turned off and DAC zeroed.")

    def reset(self) -> None:
        """
        Reset controller and session to initial IDLE state.
        """
        with self._lock:
            if self._session.state == RunState.RUNNING:
                self.stop()

            self._send_command("RESET")
            self._session.reset()

            self._target_torque = 0.0
            self._current_torque = 0.0
            self._current_torque_raw = 0.0
            self._current_rpm = 0.0
            self._current_dac = 0
            self._current_adc = 0
            self._current_step_idx = 0
            self._pid_active = False

            self._stability_monitor.reset()
            self._prev_stable = False

            self._notify("on_stability_change", False)
            self._notify("on_state_change", RunState.IDLE)
            self._notify("on_status", "Dyno reset.")

    # ------------------------------------------------------------------
    # Hardware Relays
    # ------------------------------------------------------------------

    def set_relay(self, name: str, state: bool | int) -> None:
        """Switch hardware relay (BRAKE, SENSOR, AUX)."""
        clean = str(name).strip().upper()
        val = bool(state)
        with self._lock:
            self._relays[clean] = val
            self._send_relay(clean, val)
        self._notify("on_relay", clean, val)
        self._notify("on_status", f"Relay {clean} set to {'ON' if val else 'OFF'}.")

    # ------------------------------------------------------------------
    # PID Tuning
    # ------------------------------------------------------------------

    def get_pid(self) -> None:
        """Query PID parameters stored in Arduino EEPROM."""
        self._send_command("<GET_PID>")

    def set_pid(self, kp: float, ki: float, kd: float) -> None:
        """Write new PID parameters to Arduino EEPROM."""
        for val in (kp, ki, kd):
            if not math.isfinite(val) or val < 0.0 or val > 1000.0:
                raise ValueError(f"Invalid PID parameter {val}. Must be finite in [0, 1000].")
        self._send_command(f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>")

    # ------------------------------------------------------------------
    # Torque Calibration Routine
    # ------------------------------------------------------------------

    def start_calibration(self) -> None:
        """
        Initiate maximum torque calibration procedure:
          - Powers sensor relay.
          - Sends maximum DAC output (4095).
          - Samples peak ADC reading under applied force.
        """
        with self._lock:
            self._is_calibrating = True
            self._max_calib_reading = 0.0
            self._send_command("START")
            self.set_relay("SENSOR", True)
            self._send_set_dac(4095)
        self._notify("on_status", "Torque calibration started: apply force now.")

    def finish_calibration(self) -> bool:
        """
        Complete torque calibration:
          - Zeros DAC and turns off sensor relay.
          - Updates torque_per_count if valid peak (> 512) was captured.
          - Returns True on success, False on insufficient force.
        """
        with self._lock:
            self._is_calibrating = False
            self._send_set_dac(0)
            self.set_relay("SENSOR", False)
            self._send_command("STOP")

            success = False
            if self._max_calib_reading > 512.0:
                self._calibration.torque_per_count = 5.0 / (self._max_calib_reading - 512.0)
                self._calibration.max_torque_nm = 5.0
                msg = f"Calibration successful: Peak ADC {self._max_calib_reading:.0f} mapped to 5 N·m."
                success = True
            else:
                msg = "Calibration failed: insufficient force applied."

        self._notify("on_status", msg)
        return success

    # ------------------------------------------------------------------
    # Telemetry & Logging
    # ------------------------------------------------------------------

    def start_logging(self, path: Path | str | None = None) -> Path:
        """Open CSV log file for run telemetry."""
        with self._lock:
            if self._logger.is_open():
                self._logger.close()

            if path is not None:
                p = self._logger.open_explicit(path)
            else:
                p = self._logger.open_temp()
            return p

    def stop_logging(self) -> Path | None:
        """Flush and close active log file."""
        with self._lock:
            p = self._logger.path
            if self._logger.is_open():
                self._logger.close()
            return p

    # ------------------------------------------------------------------
    # Control Loop Tick & Autonomous Background Loop
    # ------------------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        """
        Deterministic single step execution of dyno control loop:
          - Hybrid mode handoff between DAC and PID.
          - Stability evaluation and profile step gating.
          - Step timeout fallback handling.
          - Authentic telemetry sampling and CSV logging.
        """
        with self._lock:
            if self._session.state != RunState.RUNNING:
                return

            current_time = float(now) if now is not None else time.perf_counter()
            elapsed = self._session.elapsed_seconds()

            # 1. Hybrid handoff
            if self._control_mode == "hybrid":
                if not self._pid_active and self._current_rpm > 1.0:
                    self._send_set_torque(self._target_torque)
                    self._pid_active = True
                elif self._pid_active and self._current_rpm <= 1.0:
                    dac = self._calculate_open_loop_dac(self._target_torque)
                    self._send_set_dac(dac)
                    self._pid_active = False

            # 2. Evaluate stability
            is_stable = self._stability_monitor.is_stable(self._target_torque, current_time=current_time)
            if is_stable != self._prev_stable:
                self._prev_stable = is_stable
                self._notify("on_stability_change", is_stable)

            # 3. Profile stepping
            if self._session.run_mode == RunMode.PROFILE:
                if is_stable:
                    next_idx = self._current_step_idx + 1
                    if next_idx >= len(self._plf.torques):
                        self.stop()
                        self._notify("on_status", "Profile completed successfully.")
                        return
                    else:
                        self._current_step_idx = next_idx
                        self._target_torque = float(self._plf.torques[next_idx])
                        self._step_start_time = current_time
                        self._stability_monitor.reset()
                        self._prev_stable = False
                        self._notify("on_stability_change", False)
                        self._command_torque_setpoint(self._target_torque)
                        self._notify("on_step", self._current_step_idx, self._target_torque)
                        self._notify(
                            "on_status",
                            f"Stepping to setpoint {next_idx + 1}/{len(self._plf.torques)}: "
                            f"{self._target_torque:.2f} N·m",
                        )
                else:
                    # Check safety step timeout
                    if (current_time - self._step_start_time) > self._step_timeout_s:
                        warning_prefix = (
                            f"Warning: Setpoint {self._current_step_idx + 1} timed out waiting for stability."
                        )
                        next_idx = self._current_step_idx + 1
                        if next_idx >= len(self._plf.torques):
                            self.stop()
                            self._notify("on_status", f"{warning_prefix} Profile finished on timeout.")
                            return
                        else:
                            self._current_step_idx = next_idx
                            self._target_torque = float(self._plf.torques[next_idx])
                            self._step_start_time = current_time
                            self._stability_monitor.reset()
                            self._prev_stable = False
                            self._notify("on_stability_change", False)
                            self._command_torque_setpoint(self._target_torque)
                            self._notify("on_step", self._current_step_idx, self._target_torque)
                            self._notify(
                                "on_status",
                                f"{warning_prefix} Stepping to setpoint {next_idx + 1}/{len(self._plf.torques)}: "
                                f"{self._target_torque:.2f} N·m",
                            )

            # 4. Telemetry sample recording
            sample = Sample(
                elapsed_s=elapsed,
                torque_nm=self._current_torque,
                rpm=self._current_rpm,
                dac_raw=self._current_dac,
                adc_raw=self._current_adc,
                target_torque_nm=self._target_torque,
            )
            self._session.append_sample(sample)

            if self._logger.is_open():
                try:
                    self._logger.write(sample)
                except Exception:
                    pass

        self._notify("on_telemetry", sample)

    def start_loop(self, interval_s: float | None = None) -> None:
        """Start autonomous background control loop thread."""
        with self._lock:
            if self._loop_running:
                return

            tick_interval = (
                interval_s
                if interval_s is not None
                else (self._calibration.poll_interval_ms / 1000.0)
            )

            self._loop_running = True
            self._loop_stop_event.clear()
            self._loop_thread = threading.Thread(
                target=self._loop_worker,
                args=(tick_interval,),
                name="DynoEngine-ControlLoop",
                daemon=True,
            )
            self._loop_thread.start()

    def stop_loop(self) -> None:
        """Stop background control loop thread."""
        with self._lock:
            self._loop_running = False
            self._loop_stop_event.set()
            thread = self._loop_thread
            self._loop_thread = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _loop_worker(self, interval_s: float) -> None:
        while self._loop_running and not self._loop_stop_event.is_set():
            start_t = time.monotonic()
            self.tick()
            elapsed = time.monotonic() - start_t
            sleep_time = max(0.001, interval_s - elapsed)
            self._loop_stop_event.wait(timeout=sleep_time)
