"""
Serial Communication module.

Runs a dedicated QThread that owns the serial port.
All commands are queued through a thread-safe queue.
Incoming data is parsed and emitted as Qt signals.

Signals
-------
data_received(float, float, int)  – (torque_nm, speed_rpm, dac_raw)
pid_received(float, float, float) – (kp, ki, kd)
speed_received(int)               – raw ADC / speed count (kept for backward compatibility)
torque_received(float)            – measured torque (convenience)
dac_received(int)                 – current DAC output (convenience)
ack_received(str)                 – acknowledged command string
error_received(str)               – error message text
connected()                       – port opened successfully
disconnected()                    – port closed
ready()                           – Arduino sent DYNO_READY
pong_received()                   – Arduino sent PONG

Protocol (see dyno_controller.ino):
    PC  → Arduino : "START\n", "STOP\n", "RESET\n", "PING\n",
                    "<GET_PID>\n", "<SET_PID:p,i,d>\n", "<SET_TORQUE:t>\n",
                    "<SET_DAC:d>\n", "<RELAY:name,state>\n"
    Arduino → PC  : "<DATA:t,s,d>\n", "<PID_VALS:p,i,d>\n", "ACK:<cmd>\n",
                    "DYNO_READY\n", "PONG\n", "ERR:<msg>\n", "SPEED:<int>\n",
                    "DAC_INIT_ERR:<hex>\n"
"""

import math
import queue
import time
from typing import Any, Callable

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal


BAUD_RATE = 115200
READ_TIMEOUT = 0.05   # seconds — short so the thread stays responsive
WRITE_TIMEOUT = 1.0


def list_serial_ports() -> list[str]:
    """Return a list of available serial port names."""
    return sorted(p.device for p in serial.tools.list_ports.comports())


class SerialWorker(QThread):
    """
    Background thread that owns the serial port.

    Do NOT call serial methods from the GUI thread — post commands
    via send_command() or typed send_*() helpers instead.
    """

    # Telemetry and PID signals
    data_received   = pyqtSignal(float, float, int)       # (torque, speed, dac)
    pid_received    = pyqtSignal(float, float, float)     # (kp, ki, kd)
    speed_received  = pyqtSignal(int)                     # backward compatibility; int(round(speed))
    torque_received = pyqtSignal(float)                   # measured torque (convenience)
    dac_received    = pyqtSignal(int)                     # dac value (convenience)
    raw_line_received = pyqtSignal(str)                   # verbatim raw line

    # Operational signals
    ack_received    = pyqtSignal(str)                     # acknowledged command text
    error_received  = pyqtSignal(str)                     # error text
    connected       = pyqtSignal()
    disconnected    = pyqtSignal()
    ready           = pyqtSignal()                        # DYNO_READY received
    pong_received   = pyqtSignal()                        # PONG received

    def __init__(
        self,
        port: str,
        parent=None,
        boot_delay: float = 2.0,
        serial_factory: Any = serial.Serial,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._boot_delay = boot_delay
        self._serial_factory = serial_factory if serial_factory is not None else serial.Serial
        self._serial: Any = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._stop_requested = False

    # ------------------------------------------------------------------
    # Public API (call from GUI thread)
    # ------------------------------------------------------------------

    def send_command(self, cmd: str) -> None:
        """Queue a command string for sending (no trailing newline needed)."""
        self._queue.put(cmd)

    def send_start(self) -> None:
        """Queue START command to initiate closed-loop PID control."""
        self.send_command("START")

    def send_stop(self) -> None:
        """Queue STOP command to disengage PID and zero DAC output."""
        self.send_command("STOP")

    def send_reset(self) -> None:
        """Queue RESET command to clear controller state and zero DAC."""
        self.send_command("RESET")

    def send_ping(self) -> None:
        """Queue PING command to verify communication link."""
        self.send_command("PING")

    def send_get_pid(self) -> None:
        """Queue <GET_PID> command to query PID gains from Arduino EEPROM."""
        self.send_command("<GET_PID>")

    def send_set_pid(self, kp: float, ki: float, kd: float) -> None:
        """Queue <SET_PID:p,i,d> command to write new PID gains to Arduino EEPROM."""
        self.send_command(f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>")

    def send_set_torque(self, torque_nm: float) -> None:
        """Queue <SET_TORQUE:t> command to update target torque setpoint."""
        try:
            val = float(torque_nm)
            if not math.isfinite(val):
                val = 0.0
        except (ValueError, TypeError, OverflowError):
            val = 0.0
        self.send_command(f"<SET_TORQUE:{val:.2f}>")

    def send_set_dac(self, dac_val: int | float) -> None:
        """Queue <SET_DAC:d> command to set raw 12-bit DAC output (open-loop, 0-4095)."""
        try:
            val = int(round(float(dac_val)))
            if not math.isfinite(val):
                val = 0
        except (ValueError, TypeError, OverflowError):
            val = 0
        clamped = max(0, min(4095, val))
        self.send_command(f"<SET_DAC:{clamped}>")

    def send_relay(self, name: str, state: bool | int) -> None:
        """Queue <RELAY:name,state> command to switch hardware relays (BRAKE, SENSOR, AUX)."""
        val = 1 if state else 0
        clean_name = str(name).strip().upper()
        self.send_command(f"<RELAY:{clean_name},{val}>")

    def stop(self) -> None:
        """Request the thread to exit gracefully."""
        self._stop_requested = True
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        if self._stop_requested:
            return

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

        try:
            self._running = True

            # Arduino resets on USB connect — give it time to boot
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

            if not self._stop_requested:
                self._running = True
                self.connected.emit()

            while self._running and not self._stop_requested:
                # ---- Send queued commands ----
                while not self._queue.empty():
                    try:
                        cmd = self._queue.get_nowait()
                        self._serial.write(f"{cmd}\n".encode())
                    except queue.Empty:
                        break
                    except (serial.SerialException, OSError, Exception) as exc:
                        self.error_received.emit(f"Write error: {exc}")
                        self._running = False
                        break

                # ---- Read incoming lines ----
                try:
                    raw = self._serial.readline()
                except (serial.SerialException, OSError, Exception) as exc:
                    self.error_received.emit(f"Read error: {exc}")
                    self._running = False
                    break

                if raw:
                    self._parse_line(raw.decode(errors="replace").strip())

        finally:
            self._running = False
            if self._serial and getattr(self._serial, "is_open", False):
                # Safety: zero the DAC before disconnecting
                try:
                    self._serial.write(b"RESET\n")
                    time.sleep(0.1)
                except Exception:
                    pass
                try:
                    self._serial.close()
                except Exception:
                    pass
            self.disconnected.emit()

    # ------------------------------------------------------------------
    # Line parser
    # ------------------------------------------------------------------

    def _parse_line(self, line: str) -> None:
        if not line:
            return
        line = line.strip()
        if not line:
            return
            
        self.raw_line_received.emit(line)

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

                    speed_int = int(round(speed))

                    self.data_received.emit(torque, speed, dac)
                    self.speed_received.emit(speed_int)
                    self.torque_received.emit(torque)
                    self.dac_received.emit(dac)
                except Exception as exc:
                    self.error_received.emit(f"Malformed DATA frame: {line} ({exc})")

            elif line.startswith("<DATA:"):
                self.error_received.emit(f"Malformed DATA frame: {line} (missing closing '>')")

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

                    self.pid_received.emit(kp, ki, kd)
                except Exception as exc:
                    self.error_received.emit(f"Malformed PID_VALS frame: {line} ({exc})")

            elif line.startswith("<PID_VALS:"):
                self.error_received.emit(f"Malformed PID_VALS frame: {line} (missing closing '>')")

            # 3. Command Acknowledgments: ACK:...
            elif line.startswith("ACK:"):
                self.ack_received.emit(line[4:].strip())

            # 4. Link Heartbeat: PONG
            elif line == "PONG":
                self.ack_received.emit("PONG")
                self.pong_received.emit()

            # 5. Boot Notification: DYNO_READY
            elif line == "DYNO_READY":
                self.ready.emit()

            # 6. Firmware Errors: ERR:... or DAC_INIT_ERR:...
            elif line.startswith("ERR:"):
                self.error_received.emit(line[4:].strip())

            elif line.startswith("DAC_INIT_ERR:"):
                self.error_received.emit(line)

            # 7. Legacy Speed Frame: SPEED:... (Backward Compatibility)
            elif line.startswith("SPEED:"):
                try:
                    val = int(line[6:].strip())
                    self.speed_received.emit(val)
                    self.data_received.emit(0.0, float(val), 0)
                except ValueError:
                    self.error_received.emit(f"Bad SPEED value: {line}")

            # Unknown lines (e.g. startup line noise) are safely ignored
        except Exception as exc:
            self.error_received.emit(f"Unexpected parsing error for line '{line}': {exc}")
