"""
Serial Communication module.

Runs a dedicated QThread that owns the serial port.
All commands are queued through a thread-safe queue.
Incoming data is parsed and emitted as Qt signals.

Signals
-------
speed_received(int)   – raw ADC value (0-1023) from Arduino
ack_received(str)     – acknowledged command string
error_received(str)   – error message from Arduino
connected()           – port opened successfully
disconnected()        – port closed
ready()               – Arduino sent DYNO_READY

Protocol (see dyno_controller.ino):
    PC  → Arduino : "SET:<0-4095>\n", "START\n", "STOP\n", "PING\n", "RESET\n"
    Arduino → PC  : "SPEED:<int>\n", "ACK:<cmd>\n", "ERR:<msg>\n", "PONG\n", "DYNO_READY\n"
"""

import queue
import time

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
    via send_command() instead.
    """

    speed_received = pyqtSignal(int)       # raw ADC 0-1023
    ack_received   = pyqtSignal(str)       # acknowledged command label
    error_received = pyqtSignal(str)       # error text
    connected      = pyqtSignal()
    disconnected   = pyqtSignal()
    ready          = pyqtSignal()          # DYNO_READY received

    def __init__(self, port: str, parent=None) -> None:
        super().__init__(parent)
        self._port   = port
        self._serial: serial.Serial | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False

    # ------------------------------------------------------------------
    # Public API (call from GUI thread)
    # ------------------------------------------------------------------

    def send_command(self, cmd: str) -> None:
        """Queue a command string for sending (no trailing newline needed)."""
        self._queue.put(cmd)

    def stop(self) -> None:
        """Request the thread to exit gracefully."""
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._serial = serial.Serial(
                self._port,
                baudrate=BAUD_RATE,
                timeout=READ_TIMEOUT,
                write_timeout=WRITE_TIMEOUT,
            )
        except serial.SerialException as exc:
            self.error_received.emit(f"Cannot open {self._port}: {exc}")
            return

        # Arduino resets on USB connect — give it time to boot
        time.sleep(2.0)
        self._serial.reset_input_buffer()

        self._running = True
        self.connected.emit()

        try:
            while self._running:
                # ---- Send queued commands ----
                while not self._queue.empty():
                    try:
                        cmd = self._queue.get_nowait()
                        self._serial.write(f"{cmd}\n".encode())
                    except queue.Empty:
                        break
                    except serial.SerialException as exc:
                        self.error_received.emit(f"Write error: {exc}")
                        self._running = False
                        break

                # ---- Read incoming lines ----
                try:
                    raw = self._serial.readline()
                except serial.SerialException as exc:
                    self.error_received.emit(f"Read error: {exc}")
                    self._running = False
                    break

                if raw:
                    self._parse_line(raw.decode(errors="replace").strip())

        finally:
            if self._serial and self._serial.is_open:
                # Safety: zero the DAC before disconnecting
                try:
                    self._serial.write(b"RESET\n")
                    time.sleep(0.1)
                except Exception:
                    pass
                self._serial.close()
            self.disconnected.emit()

    # ------------------------------------------------------------------
    # Line parser
    # ------------------------------------------------------------------

    def _parse_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("SPEED:"):
            try:
                val = int(line[6:].strip())
                self.speed_received.emit(val)
            except ValueError:
                self.error_received.emit(f"Bad SPEED value: {line}")
        elif line.startswith("ACK:"):
            self.ack_received.emit(line[4:].strip())
        elif line.startswith("ERR:"):
            self.error_received.emit(line[4:].strip())
        elif line == "PONG":
            self.ack_received.emit("PONG")
        elif line == "DYNO_READY":
            self.ready.emit()
        # Ignore unknown lines silently
