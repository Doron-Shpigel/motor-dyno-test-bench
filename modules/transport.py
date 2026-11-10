"""
Pure Python Transport module for motor-dyno-test-bench.

Provides threaded serial transport and mock transport for headless dyno operation.
Decoupled entirely from PyQt6 / GUI frameworks.
"""

from abc import ABC, abstractmethod
import math
import queue
import random
import threading
import time
from typing import Any, Callable

import serial
import serial.tools.list_ports


BAUD_RATE = 115200
READ_TIMEOUT = 0.05   # seconds
WRITE_TIMEOUT = 1.0


def list_serial_ports() -> list[str]:
    """Return a sorted list of available serial port device names."""
    return sorted(p.device for p in serial.tools.list_ports.comports())


class BaseTransport(ABC):
    """
    Abstract base transport interface defining callbacks and typed send helpers.
    """

    def __init__(
        self,
        on_data: Callable[[float, float, int], None] | None = None,
        on_pid: Callable[[float, float, float], None] | None = None,
        on_ack: Callable[[str], None] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self.on_data = on_data
        self.on_pid = on_pid
        self.on_ack = on_ack
        self.on_ready = on_ready
        self.on_error = on_error
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected

    def _emit(self, callback_name: str, *args: Any, **kwargs: Any) -> None:
        """Safely invoke registered callback without crashing the transport thread."""
        cb = getattr(self, callback_name, None)
        if cb is not None and callable(cb):
            try:
                cb(*args, **kwargs)
            except Exception as exc:
                if callback_name != "on_error":
                    self._emit("on_error", f"Error in {callback_name} callback: {exc}")

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the transport is active and connected."""
        pass

    @abstractmethod
    def connect(self, port: str | None = None, baudrate: int | None = None) -> None:
        """Connect to the target device or start transport."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and release resources."""
        pass

    @abstractmethod
    def send_command(self, cmd: str) -> None:
        """Send raw command string (newline added automatically)."""
        pass

    # ------------------------------------------------------------------
    # Typed send helpers
    # ------------------------------------------------------------------

    def send_start(self) -> None:
        """Initiate closed-loop PID control."""
        self.send_command("START")

    def send_stop(self) -> None:
        """Disengage PID and zero DAC output."""
        self.send_command("STOP")

    def send_reset(self) -> None:
        """Clear controller state and zero DAC."""
        self.send_command("RESET")

    def send_ping(self) -> None:
        """Verify communication link."""
        self.send_command("PING")

    def send_get_pid(self) -> None:
        """Query PID gains from Arduino EEPROM."""
        self.send_command("<GET_PID>")

    def send_set_pid(self, kp: float, ki: float, kd: float) -> None:
        """Write new PID gains to Arduino EEPROM."""
        self.send_command(f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>")

    def send_set_torque(self, torque_nm: float) -> None:
        """Update target torque setpoint (N·m)."""
        try:
            val = float(torque_nm)
            if not math.isfinite(val):
                val = 0.0
        except (ValueError, TypeError, OverflowError):
            val = 0.0
        self.send_command(f"<SET_TORQUE:{val:.2f}>")

    def send_set_dac(self, dac_val: int | float) -> None:
        """Set raw 12-bit DAC output (open-loop, 0-4095)."""
        try:
            val = int(round(float(dac_val)))
            if not math.isfinite(val):
                val = 0
        except (ValueError, TypeError, OverflowError):
            val = 0
        clamped = max(0, min(4095, val))
        self.send_command(f"<SET_DAC:{clamped}>")

    def send_relay(self, name: str, state: bool | int) -> None:
        """Switch hardware relays (e.g. BRAKE, SENSOR, AUX)."""
        val = 1 if state else 0
        clean_name = str(name).strip().upper()
        self.send_command(f"<RELAY:{clean_name},{val}>")

    # ------------------------------------------------------------------
    # Telemetry line parser
    # ------------------------------------------------------------------

    def parse_line(self, line: str) -> None:
        """Parse incoming line from Arduino and dispatch appropriate callbacks."""
        if not line:
            return
        line = line.strip()
        if not line:
            return

        try:
            # 1. Telemetry Packet: <DATA:t,s,d>
            if line.startswith("<DATA:") and line.endswith(">"):
                payload = line[6:-1]
                try:
                    parts = payload.split(",")
                    if len(parts) != 3:
                        raise ValueError(f"Expected 3 fields, got {len(parts)}")
                    torque = float(parts[0].strip())
                    speed = float(parts[1].strip())
                    dac = int(parts[2].strip())

                    if not (math.isfinite(torque) and math.isfinite(speed)):
                        raise ValueError("Non-finite numeric values in DATA frame")

                    self._emit("on_data", torque, speed, dac)
                except Exception as exc:
                    self._emit("on_error", f"Malformed DATA frame: {line} ({exc})")

            elif line.startswith("<DATA:"):
                self._emit("on_error", f"Malformed DATA frame: {line} (missing closing '>')")

            # 2. PID Values Packet: <PID_VALS:p,i,d>
            elif line.startswith("<PID_VALS:") and line.endswith(">"):
                payload = line[10:-1]
                try:
                    parts = payload.split(",")
                    if len(parts) != 3:
                        raise ValueError(f"Expected 3 fields, got {len(parts)}")
                    kp = float(parts[0].strip())
                    ki = float(parts[1].strip())
                    kd = float(parts[2].strip())

                    if not (math.isfinite(kp) and math.isfinite(ki) and math.isfinite(kd)):
                        raise ValueError("Non-finite values in PID frame")

                    self._emit("on_pid", kp, ki, kd)
                except Exception as exc:
                    self._emit("on_error", f"Malformed PID_VALS frame: {line} ({exc})")

            elif line.startswith("<PID_VALS:"):
                self._emit("on_error", f"Malformed PID_VALS frame: {line} (missing closing '>')")

            # 3. Command Acknowledgments: ACK:...
            elif line.startswith("ACK:"):
                self._emit("on_ack", line[4:].strip())

            # 4. Link Heartbeat: PONG
            elif line == "PONG":
                self._emit("on_ack", "PONG")

            # 5. Boot Notification: DYNO_READY
            elif line == "DYNO_READY":
                self._emit("on_ready")

            # 6. Firmware Errors: ERR:... or DAC_INIT_ERR:...
            elif line.startswith("ERR:"):
                self._emit("on_error", line[4:].strip())

            elif line.startswith("DAC_INIT_ERR:"):
                self._emit("on_error", line)

            # 7. Legacy Speed Frame: SPEED:...
            elif line.startswith("SPEED:"):
                try:
                    val = int(line[6:].strip())
                    self._emit("on_data", 0.0, float(val), 0)
                except ValueError:
                    self._emit("on_error", f"Bad SPEED value: {line}")

        except Exception as exc:
            self._emit("on_error", f"Unexpected parsing error for line '{line}': {exc}")


class SerialTransport(BaseTransport):
    """
    Standard serial transport running in a dedicated threading.Thread.
    """

    def __init__(
        self,
        port: str = "",
        baudrate: int = BAUD_RATE,
        boot_delay: float = 2.0,
        serial_factory: Any = serial.Serial,
        read_timeout: float = READ_TIMEOUT,
        write_timeout: float = WRITE_TIMEOUT,
        on_data: Callable[[float, float, int], None] | None = None,
        on_pid: Callable[[float, float, float], None] | None = None,
        on_ack: Callable[[str], None] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            on_data=on_data,
            on_pid=on_pid,
            on_ack=on_ack,
            on_ready=on_ready,
            on_error=on_error,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )
        self._port = port
        self._baudrate = baudrate
        self._boot_delay = boot_delay
        self._serial_factory = serial_factory if serial_factory is not None else serial.Serial
        self._read_timeout = read_timeout
        self._write_timeout = write_timeout

        self._serial: Any = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_requested = False

    @property
    def is_connected(self) -> bool:
        return self._running and self._serial is not None and getattr(self._serial, "is_open", False)

    @property
    def port(self) -> str:
        return self._port

    def connect(self, port: str | None = None, baudrate: int | None = None) -> None:
        if port is not None:
            self._port = port
        if baudrate is not None:
            self._baudrate = baudrate

        if self.is_connected:
            self.disconnect()

        self._stop_requested = False
        self._running = False
        self._thread = threading.Thread(target=self._run, name=f"SerialTransport-{self._port}", daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop_requested = True
        self._running = False
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def send_command(self, cmd: str) -> None:
        self._queue.put(cmd)

    def _run(self) -> None:
        if self._stop_requested:
            return

        try:
            self._serial = self._serial_factory(
                self._port,
                baudrate=self._baudrate,
                timeout=self._read_timeout,
                write_timeout=self._write_timeout,
            )
        except (serial.SerialException, OSError, Exception) as exc:
            self._emit("on_error", f"Cannot open {self._port}: {exc}")
            return

        try:
            self._running = True

            # Arduino resets on USB connect — boot delay
            if self._boot_delay > 0:
                end_time = time.monotonic() + self._boot_delay
                while time.monotonic() < end_time:
                    if self._stop_requested or not self._running:
                        return
                    time.sleep(0.05)

            if self._stop_requested or not self._running:
                return

            if hasattr(self._serial, "reset_input_buffer"):
                try:
                    self._serial.reset_input_buffer()
                except Exception:
                    pass

            if self._stop_requested or not self._running:
                return

            self._emit("on_connected")

            while self._running and not self._stop_requested:
                # Draining send queue
                while not self._queue.empty():
                    try:
                        cmd = self._queue.get_nowait()
                        self._serial.write(f"{cmd}\n".encode())
                    except queue.Empty:
                        break
                    except (serial.SerialException, OSError, Exception) as exc:
                        self._emit("on_error", f"Write error: {exc}")
                        self._running = False
                        break

                # Reading lines
                try:
                    raw = self._serial.readline()
                except (serial.SerialException, OSError, Exception) as exc:
                    self._emit("on_error", f"Read error: {exc}")
                    self._running = False
                    break

                if raw:
                    self.parse_line(raw.decode(errors="replace").strip())

        finally:
            self._running = False
            if self._serial and getattr(self._serial, "is_open", False):
                try:
                    self._serial.write(b"RESET\n")
                    time.sleep(0.05)
                except Exception:
                    pass
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._emit("on_disconnected")


class MockTransport(BaseTransport):
    """
    In-memory mock transport for deterministic testing and headless simulation.
    """

    def __init__(
        self,
        port: str = "MOCK",
        auto_ack: bool = False,
        on_data: Callable[[float, float, int], None] | None = None,
        on_pid: Callable[[float, float, float], None] | None = None,
        on_ack: Callable[[str], None] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            on_data=on_data,
            on_pid=on_pid,
            on_ack=on_ack,
            on_ready=on_ready,
            on_error=on_error,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )
        self.port = port
        self.auto_ack = auto_ack
        self.sent_commands: list[str] = []
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, port: str | None = None, baudrate: int | None = None) -> None:
        if port is not None:
            self.port = port
        self._connected = True
        self._emit("on_connected")

    def disconnect(self) -> None:
        if self._connected:
            self._connected = False
            self._emit("on_disconnected")

    def send_command(self, cmd: str) -> None:
        self.sent_commands.append(cmd)
        if self.auto_ack:
            if cmd == "PING":
                self._emit("on_ack", "PONG")
            elif cmd == "<GET_PID>":
                self._emit("on_pid", 100.0, 10.0, 1.0)
            else:
                clean = cmd.strip("<>")
                self._emit("on_ack", clean)

    # ------------------------------------------------------------------
    # Simulation helpers
    # ------------------------------------------------------------------

    def simulate_data(self, torque: float, speed_rpm: float, dac_raw: int) -> None:
        """Simulate receipt of a <DATA:t,s,d> packet."""
        self._emit("on_data", torque, speed_rpm, dac_raw)

    def simulate_pid(self, kp: float, ki: float, kd: float) -> None:
        """Simulate receipt of a <PID_VALS:p,i,d> packet."""
        self._emit("on_pid", kp, ki, kd)

    def simulate_ack(self, cmd: str) -> None:
        """Simulate receipt of an ACK:<cmd> packet."""
        self._emit("on_ack", cmd)

    def simulate_ready(self) -> None:
        """Simulate receipt of DYNO_READY."""
        self._emit("on_ready")

    def simulate_error(self, msg: str) -> None:
        """Simulate receipt of an error message."""
        self._emit("on_error", msg)

    def simulate_raw_line(self, line: str) -> None:
        """Simulate raw wire line to test parsing."""
        self.parse_line(line)


class SimulatedTransport(MockTransport):
    """
    Simulated dyno hardware transport with realistic motor physics for demo mode and testing.

    Simulates:
      - Motor spinup and speed droop under load.
      - Closed-loop torque tracking to commanded setpoint with stability.
      - Open-loop DAC voltage-to-torque conversion.
      - Hardware relay handling and emergency stop.
      - Torque sensor calibration peak detection.
      - Automatic response to <GET_PID>, <SET_PID>, PING, START, STOP, RESET.
    """

    def __init__(
        self,
        port: str = "DEMO_PORT",
        auto_ack: bool = True,
        tick_interval_s: float = 0.05,
        target_rpm: float = 2800.0,
        max_torque_nm: float = 5.0,
        on_data: Callable[[float, float, int], None] | None = None,
        on_pid: Callable[[float, float, float], None] | None = None,
        on_ack: Callable[[str], None] | None = None,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            port=port,
            auto_ack=auto_ack,
            on_data=on_data,
            on_pid=on_pid,
            on_ack=on_ack,
            on_ready=on_ready,
            on_error=on_error,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )
        self.tick_interval_s = float(tick_interval_s)
        self.target_rpm = float(target_rpm)
        self.max_torque_nm = float(max_torque_nm)

        self._sim_thread: threading.Thread | None = None
        self._sim_stop_event = threading.Event()
        self._sim_lock = threading.Lock()

        # Physics simulation state
        self._motor_running = False
        self._sim_rpm = 0.0
        self._sim_torque = 0.0
        self._target_torque = 0.0
        self._dac_val = 0
        self._stored_pid: tuple[float, float, float] = (100.0, 10.0, 1.0)
        self._relays: dict[str, bool] = {"BRAKE": False, "SENSOR": False, "AUX": False}
        self._is_calibrating = False

    def connect(self, port: str | None = None, baudrate: int | None = None) -> None:
        if port is not None:
            self.port = port
        self._connected = True
        self._sim_stop_event.clear()
        self._emit("on_connected")
        self._emit("on_ready")

        if self._sim_thread is None or not self._sim_thread.is_alive():
            self._sim_thread = threading.Thread(
                target=self._run_simulation,
                name="DynoSimulatedTransport",
                daemon=True,
            )
            self._sim_thread.start()

    def disconnect(self) -> None:
        if self._connected:
            self._connected = False
            self._sim_stop_event.set()
            thread = self._sim_thread
            self._sim_thread = None
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)
            self._emit("on_disconnected")

    def send_command(self, cmd: str) -> None:
        self.sent_commands.append(cmd)
        clean = cmd.strip()

        with self._sim_lock:
            if clean == "START":
                self._motor_running = True
                self._emit("on_ack", "START")
            elif clean == "STOP":
                self._motor_running = False
                self._target_torque = 0.0
                self._dac_val = 0
                for r in self._relays:
                    self._relays[r] = False
                self._is_calibrating = False
                self._emit("on_ack", "STOP")
            elif clean == "RESET":
                self._motor_running = False
                self._sim_rpm = 0.0
                self._sim_torque = 0.0
                self._target_torque = 0.0
                self._dac_val = 0
                self._is_calibrating = False
                self._emit("on_ack", "RESET")
            elif clean == "PING":
                self._emit("on_ack", "PONG")
            elif clean == "<GET_PID>":
                self._emit("on_pid", *self._stored_pid)
            elif clean.startswith("<SET_PID:"):
                val_str = clean[9:-1]
                try:
                    parts = [float(x) for x in val_str.split(",")]
                    if len(parts) == 3:
                        self._stored_pid = (parts[0], parts[1], parts[2])
                        self._emit("on_ack", f"SET_PID:{parts[0]:.4f},{parts[1]:.4f},{parts[2]:.4f}")
                        self._emit("on_pid", *self._stored_pid)
                except Exception:
                    pass
            elif clean.startswith("<SET_TORQUE:"):
                val_str = clean[12:-1]
                try:
                    self._target_torque = max(0.0, float(val_str))
                    self._emit("on_ack", f"SET_TORQUE:{self._target_torque:.2f}")
                except Exception:
                    pass
            elif clean.startswith("<SET_DAC:"):
                val_str = clean[9:-1]
                try:
                    self._dac_val = max(0, min(4095, int(val_str)))
                    self._emit("on_ack", f"SET_DAC:{self._dac_val}")
                    if self._relays.get("SENSOR", False) and self._dac_val >= 4000:
                        self._is_calibrating = True
                except Exception:
                    pass
            elif clean.startswith("<RELAY:"):
                content = clean[7:-1]
                parts = content.split(",")
                if len(parts) == 2:
                    name = parts[0].strip().upper()
                    st = bool(int(parts[1].strip()))
                    self._relays[name] = st
                    self._emit("on_ack", f"RELAY:{name},{1 if st else 0}")
            else:
                if self.auto_ack:
                    self._emit("on_ack", clean.strip("<>"))

    def _run_simulation(self) -> None:
        dt = self.tick_interval_s
        torque_per_count = 5.0 / (1023.0 - 512.0)
        rpm_per_count = 0.5

        while self._connected and not self._sim_stop_event.is_set():
            loop_start = time.monotonic()

            with self._sim_lock:
                if self._motor_running:
                    load_sag = self._sim_torque * 100.0
                    goal_rpm = max(400.0, self.target_rpm - load_sag)
                    self._sim_rpm += (goal_rpm - self._sim_rpm) * min(1.0, dt * 6.0)

                    if self._target_torque > 0.0:
                        goal_torque = self._target_torque
                    elif self._dac_val > 0:
                        goal_torque = (self._dac_val / 4095.0) * self.max_torque_nm
                    else:
                        goal_torque = 0.0

                    self._sim_torque += (goal_torque - self._sim_torque) * min(1.0, dt * 7.0)
                    noise = (random.random() - 0.5) * 0.008
                    current_torque = max(0.0, self._sim_torque + noise)
                else:
                    self._sim_rpm += (0.0 - self._sim_rpm) * min(1.0, dt * 5.0)
                    if self._sim_rpm < 1.0:
                        self._sim_rpm = 0.0
                    self._sim_torque += (0.0 - self._sim_torque) * min(1.0, dt * 5.0)
                    if self._sim_torque < 0.005:
                        self._sim_torque = 0.0
                    current_torque = self._sim_torque

                if self._is_calibrating:
                    torque_adc = 930.0 + (random.random() - 0.5) * 4.0
                else:
                    torque_adc = 512.0 + (current_torque / torque_per_count)

                speed_adc = self._sim_rpm / rpm_per_count
                dac_raw = self._dac_val

            self._emit("on_data", torque_adc, speed_adc, dac_raw)

            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.005, dt - elapsed)
            self._sim_stop_event.wait(timeout=sleep_time)

