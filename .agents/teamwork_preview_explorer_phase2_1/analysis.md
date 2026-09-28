# Comprehensive Analysis: Requirement 1 (R1) Serial Protocol Overhaul

**Investigator**: Explorer 1 (Serial Protocol Explorer)  
**Date**: 2026-09-28  
**Component**: `modules/serial_comm.py` and `arduino/dyno_controller/dyno_controller.ino`  
**Status**: Completed  

---

## 1. Executive Summary

Requirement 1 (R1) represents the foundational communication layer for Phase 2 of the Motor Dyno Test Bench. In Phase 1, communication was rudimentary: the PC periodically sent an open-loop DAC command (`SET:<0-4095>`), while the Arduino sent periodic raw analog speed readings (`SPEED:<0-1023>`). 

In Phase 2, the dyno controller firmware (`arduino/dyno_controller/dyno_controller.ino`) has transitioned to an autonomous, closed-loop PID control system running at 50 Hz on the microcontroller. Consequently:
1. The PC no longer controls the raw DAC directly during a test run; instead, it commands closed-loop torque targets (`<SET_TORQUE:t>`).
2. The Arduino transmits comprehensive telemetry packets at 20 Hz (every 50 ms): `<DATA:t,s,d>` representing physical torque, physical speed, and the internally computed DAC command.
3. The PC must inspect and tune the onboard PID parameters (`Kp, Ki, Kd`) stored in the Arduino's EEPROM via `<GET_PID>` and `<SET_PID:p,i,d>`, receiving `<PID_VALS:p,i,d>`.
4. Acknowledgments (`ACK:...`), ping responses (`PONG`), and boot readiness notifications (`DYNO_READY`) must be parsed and dispatched as typed PyQt6 signals.
5. `SerialWorker` in `modules/serial_comm.py` must maintain 100% backward compatibility for existing consumers (such as `main_window.py`'s `speed_received` slot) until Milestone 3 refactoring is implemented.

---

## 2. Firmware Analysis: `arduino/dyno_controller/dyno_controller.ino`

Inspection of the Arduino sketch reveals the exact contract governing the physical microcontroller:

### 2.1 Communication Parameters & Timing
- **Baud Rate**: `115200` (`#define SERIAL_BAUD 115200` at line 8; `Serial.begin(SERIAL_BAUD)` at line 58). Matches `BAUD_RATE = 115200` in `modules/serial_comm.py`.
- **Microcontroller Loops**:
  - **PID Control Loop**: Period `PID_INTERVAL = 20` ms (50 Hz, lines 87–129). Reads `A0` (Torque) and `A1` (Speed).
  - **PC Telemetry Loop**: Period `TELEMETRY_INTERVAL = 50` ms (20 Hz, lines 134–143).
- **Line Endings**: Microcontroller commands are processed on newline `\n` (line 152). Microcontroller responses are terminated with `\r\n` (via `Serial.println()`).

### 2.2 Bootup Sequence
- Line 73: `Serial.println(F("DYNO_READY"));`
- Trigger: Sent once when `setup()` completes.
- Notes: Arduino boards (Uno/Nano) reset when the serial port is opened via USB due to the DTR toggle. `SerialWorker` sleeps for 2.0 seconds upon opening to allow this bootup and EEPROM load to finish.

### 2.3 Telemetry Output: `<DATA:t,s,d>`
- Generated in `loop()` lines 136–142:
  ```cpp
  Serial.print("<DATA:");
  Serial.print(currentTorque, 2); Serial.print(",");
  Serial.print(currentSpeed, 2); Serial.print(",");
  Serial.print(dacValue);
  Serial.println(">");
  ```
- **Field 1 (`t`)**: `currentTorque` (float, formatted to 2 decimals). Analog reading from `TORQUE_PIN` (A0). Example: `12.34`.
- **Field 2 (`s`)**: `currentSpeed` (float, formatted to 2 decimals). Analog reading from `SPEED_PIN` (A1). Example: `1520.50`.
- **Field 3 (`d`)**: `dacValue` (integer, 0 to 4095). MCP4725 12-bit DAC brake command. Example: `2048`.
- **Sample Frame**: `<DATA:12.34,1520.50,2048>\r\n`.

### 2.4 Command Processing (`processCommand`)
The Arduino serial parser reads characters into `serialBuffer` until `\n`. It then invokes `processCommand(cmd)` after calling `cmd.trim()` (line 163).

| Incoming Command from PC | Arduino Firmware Action | Arduino Response to PC | Notes |
|:---|:---|:---|:---|
| `START` | `isRunning = true;` (line 168) | `ACK:START\r\n` | Activates closed-loop PID control. |
| `STOP` | `isRunning = false; targetTorque = 0.0; errorIntegral = 0.0; mcp4725_write(0);` (lines 172-175) | `ACK:STOP\r\n` | Deactivates PID, zeroes brake immediately. |
| `RESET` | Same as `STOP` (lines 172-175) | `ACK:RESET\r\n` | Deactivates PID, zeroes brake, clears integral. |
| `PING` | None (line 179) | `PONG\r\n` | Heartbeat / link verification. |
| `<GET_PID>` | Reads `pid` struct from RAM (line 182) | `<PID_VALS:p,i,d>\r\n` (e.g. `<PID_VALS:100.0000,10.0000,1.0000>`) | Gains printed with 4 decimals. |
| `<SET_PID:p,i,d>` | Extracts floats, saves to EEPROM, resets `errorIntegral = 0` (lines 189-201) | `ACK:SET_PID\r\n` | Updates Kp, Ki, Kd in persistent storage. |
| `<SET_TORQUE:t>` | Extracts float `targetTorque = cmd.substring(...).toFloat()` (lines 204-209) | `ACK:SET_TORQUE:<value>\r\n` (e.g. `ACK:SET_TORQUE:15.50`) | Updates active setpoint for PID loop. |

### 2.5 Deprecated Commands
- **`SET:<dac>`**: Used in Phase 1 for open-loop control. **Not present in `dyno_controller.ino`**. Any `SET:...` command sent to the new firmware is ignored silently.

---

## 3. Detailed Design of `modules/serial_comm.py`

### 3.1 Qt Signal Signatures
`SerialWorker` must expose the following Qt signals:

```python
class SerialWorker(QThread):
    # Phase 2 Core Telemetry and PID Signals
    data_received  = pyqtSignal(float, float, int)       # (torque, speed, dac)
    pid_received   = pyqtSignal(float, float, float)     # (kp, ki, kd)
    pong_received  = pyqtSignal()                        # PONG response

    # Operational & Lifecycle Signals
    ack_received   = pyqtSignal(str)                     # command acknowledgment text
    error_received = pyqtSignal(str)                     # error message text
    connected      = pyqtSignal()                        # serial port opened successfully
    disconnected   = pyqtSignal()                        # serial port closed
    ready          = pyqtSignal()                        # DYNO_READY received from firmware

    # Backward-Compatibility & Granular Telemetry Signals
    speed_received  = pyqtSignal(int)                    # raw speed/ADC count (int)
    torque_received = pyqtSignal(float)                  # granular torque signal (optional)
    dac_received    = pyqtSignal(int)                    # granular dac signal (optional)
```

### 3.2 Parsing Specifications & Robustness Logic
When reading lines in the worker thread loop:
`raw = self._serial.readline()`  
`line = raw.decode(errors="replace").strip()`

`_parse_line(line: str)` must evaluate conditions in this order:

1. **Empty Line Check**:
   If not `line`, return immediately.

2. **Telemetry Frame `<DATA:...>`**:
   - Check: `line.startswith("<DATA:") and line.endswith(">")`
   - Payload extraction: `payload = line[6:-1]`
   - Split: `parts = payload.split(",")`
   - Validation: Must have exactly 3 tokens.
   - Parsing:
     - `torque = float(parts[0].strip())`
     - `speed = float(parts[1].strip())`
     - `dac = int(parts[2].strip())`
   - Emissions:
     - `self.data_received.emit(torque, speed, dac)`
     - `self.speed_received.emit(int(round(speed)))` (backward compatibility)
     - `self.torque_received.emit(torque)` (convenience)
     - `self.dac_received.emit(dac)` (convenience)
   - Error Handling: On `ValueError` or `IndexError`:
     `self.error_received.emit(f"Malformed DATA frame: {line}")`

3. **PID Parameters Frame `<PID_VALS:...>`**:
   - Check: `line.startswith("<PID_VALS:") and line.endswith(">")`
   - Payload extraction: `payload = line[10:-1]`
   - Split: `parts = payload.split(",")`
   - Validation: Must have exactly 3 tokens.
   - Parsing:
     - `kp = float(parts[0].strip())`
     - `ki = float(parts[1].strip())`
     - `kd = float(parts[2].strip())`
   - Emissions:
     - `self.pid_received.emit(kp, ki, kd)`
   - Error Handling: On `ValueError` or `IndexError`:
     `self.error_received.emit(f"Malformed PID_VALS frame: {line}")`

4. **Acknowledgment `ACK:...`**:
   - Check: `line.startswith("ACK:")`
   - Payload extraction: `ack_text = line[4:].strip()`
   - Emission: `self.ack_received.emit(ack_text)`
   - Note: For `ACK:START`, emits `"START"`. For `ACK:SET_TORQUE:15.50`, emits `"SET_TORQUE:15.50"`.

5. **Ping Response `PONG`**:
   - Check: `line == "PONG"`
   - Emissions:
     - `self.ack_received.emit("PONG")` (maintains existing contract)
     - `self.pong_received.emit()`

6. **Firmware Ready `DYNO_READY`**:
   - Check: `line == "DYNO_READY"`
   - Emission: `self.ready.emit()`

7. **Error Message `ERR:...`**:
   - Check: `line.startswith("ERR:")`
   - Emission: `self.error_received.emit(line[4:].strip())`

8. **Legacy Frame `SPEED:...` (Backward Compatibility)**:
   - Check: `line.startswith("SPEED:")`
   - Parsing: `val = int(line[6:].strip())`
   - Emissions:
     - `self.speed_received.emit(val)`
     - `self.data_received.emit(0.0, float(val), 0)`

9. **Unrecognized Traffic**:
   - Any unknown string (e.g. line noise during USB plug-in) is safely ignored without crashing.

### 3.3 Outgoing Command Methods
In addition to generic `send_command(cmd: str)`, `SerialWorker` should provide typed helper methods to prevent formatting discrepancies:

```python
def send_command(self, cmd: str) -> None:
    """Queue raw command string (newline appended automatically)."""
    self._queue.put(cmd)

def send_start(self) -> None:
    """Send START command to engage closed-loop PID control."""
    self.send_command("START")

def send_stop(self) -> None:
    """Send STOP command to disengage PID and zero DAC output."""
    self.send_command("STOP")

def send_reset(self) -> None:
    """Send RESET command to reset controller state and zero DAC."""
    self.send_command("RESET")

def send_ping(self) -> None:
    """Send PING command to verify Arduino link liveness."""
    self.send_command("PING")

def send_get_pid(self) -> None:
    """Send <GET_PID> command to query stored gains from Arduino EEPROM."""
    self.send_command("<GET_PID>")

def send_set_pid(self, kp: float, ki: float, kd: float) -> None:
    """Send <SET_PID:p,i,d> command to update EEPROM PID gains."""
    self.send_command(f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>")

def send_set_torque(self, torque_nm: float) -> None:
    """Send <SET_TORQUE:t> command to update target torque setpoint."""
    self.send_command(f"<SET_TORQUE:{torque_nm:.2f}>")
```

### 3.4 Safety on Disconnect
Lines 125–129 in existing `serial_comm.py`:
```python
if self._serial and self._serial.is_open:
    try:
        self._serial.write(b"RESET\n")
        time.sleep(0.1)
    except Exception:
        pass
    self._serial.close()
```
This is fully compatible with `dyno_controller.ino` line 171–177, which executes `mcp4725_write(0)` and zeroes `targetTorque` upon receiving `RESET`.

---

## 4. Integration & Backward Compatibility

### 4.1 Compatibility with `gui/main_window.py`
In `main_window.py`:
- Line 258: `self._worker.speed_received.connect(self._on_speed_received)`
- Line 291: `def _on_speed_received(self, adc_val: int) -> None:`
By emitting `self.speed_received.emit(int(round(speed)))` whenever `<DATA:t,s,d>` is parsed, `main_window.py` continues to receive speed telemetry without crashing or requiring immediate Milestone 3 modifications.

### 4.2 Forward Wiring for Milestone 2 (`pid_tuning_tab.py`)
In `pid_tuning_tab.py`:
- `set_stored_values(kp: float, ki: float, kd: float)` (line 262) matches the parameters of `pid_received = pyqtSignal(float, float, float)`.
- Connecting `serial_worker.pid_received.connect(pid_tab.set_stored_values)` allows instantaneous update of UI stored PID readouts when `<PID_VALS:...>` arrives.

### 4.3 Forward Wiring for Milestone 3 (`main_window.py` Closed-Loop & Stability)
In Milestone 3:
- `main_window.py` connects `self._worker.data_received.connect(self._on_data_received)`.
- `_on_data_received(torque: float, speed: float, dac: int)` will push measured `torque` to `StabilityMonitor.add_reading(torque, time.perf_counter())`.
- `_on_tick` will send `<SET_TORQUE:torque_nm>` via `send_set_torque(torque_nm)` instead of `SET:<dac>`.

---

## 5. Testing & Verification Strategy

### 5.1 Test Environment Constraints
- Test Runner: Standard library `unittest` via `.env/bin/python -m unittest discover tests` (fast, deterministic, zero third-party dependencies required).
- Headless Qt Execution: Tests importing PyQt6 must set `os.environ["QT_QPA_PLATFORM"] = "offscreen"` or instantiate `QCoreApplication` to avoid GUI server requirements.

### 5.2 Test Architecture: 4 Independent Test Suites in `tests/test_serial_comm.py`

#### Suite 1: Pure Parser Unit Tests (`TestSerialLineParser`)
Directly invokes `worker._parse_line(line)` and verifies signal emissions synchronously without threading:
- `test_parse_data_normal`: `<DATA:12.34,1520.50,2048>` -> checks `data_received(12.34, 1520.50, 2048)` and `speed_received(1521)`.
- `test_parse_data_zero_and_negative`: `<DATA:0.00,0.00,0>` and `<DATA:-2.50,800.00,100>` -> checks correct numeric conversions.
- `test_parse_data_malformed`: Incomplete tokens (`<DATA:12.34,2048>`), non-numeric (`<DATA:abc,10,20>`), missing delimiters -> verifies `error_received` emission and zero crashes.
- `test_parse_pid_vals_normal`: `<PID_VALS:100.0000,10.0000,1.0000>` -> checks `pid_received(100.0, 10.0, 1.0)`.
- `test_parse_pid_vals_malformed`: `<PID_VALS:10,20>`, `<PID_VALS:bad,1,2>` -> verifies `error_received` emission.
- `test_parse_acks`: `ACK:START`, `ACK:STOP`, `ACK:RESET`, `ACK:SET_PID`, `ACK:SET_TORQUE:15.50` -> verifies `ack_received` emissions.
- `test_parse_pong`: `PONG` -> verifies `ack_received("PONG")` and `pong_received()`.
- `test_parse_ready`: `DYNO_READY` -> verifies `ready()`.
- `test_parse_legacy_speed`: `SPEED:512` -> verifies `speed_received(512)` and `data_received(0.0, 512.0, 0)`.
- `test_parse_unknown_noise`: Empty string `""` and random garbage `"###CORRUPT###"` -> safely handled without errors.

#### Suite 2: Command Queueing & Formatting Tests (`TestSerialWorkerCommands`)
Tests the typed helper methods without running threads:
- Verify that `send_start()` queues `"START"`.
- Verify that `send_stop()` queues `"STOP"`.
- Verify that `send_reset()` queues `"RESET"`.
- Verify that `send_ping()` queues `"PING"`.
- Verify that `send_get_pid()` queues `"<GET_PID>"`.
- Verify that `send_set_pid(120.5, 15.25, 1.1)` queues `"<SET_PID:120.5000,15.2500,1.1000>"`.
- Verify that `send_set_torque(25.4)` queues `"<SET_TORQUE:25.40>"`.

#### Suite 3: Headless Thread Execution with `FakeSerial` (`TestSerialWorkerThread`)
Emulates full asynchronous worker thread operation using a deterministic mock serial device:
```python
class FakeSerial:
    def __init__(self, port, baudrate, timeout, write_timeout):
        self.is_open = True
        self.written_bytes = []
        self.lines = [
            b"DYNO_READY\n",
            b"<DATA:10.50,1400.00,1024>\n",
            b"<PID_VALS:100.0000,10.0000,1.0000>\n",
            b"ACK:START\n",
        ]

    def reset_input_buffer(self): pass

    def readline(self):
        if self.lines:
            return self.lines.pop(0)
        return b""

    def write(self, data):
        self.written_bytes.append(data)

    def close(self):
        self.is_open = False
```
- In tests, supply `boot_delay=0.0` to avoid the 2.0s sleep penalty.
- Start `worker.start()`, send command `worker.send_command("START")`.
- Call `worker.stop()` and `worker.wait(1000)`.
- Flush cross-thread events via `QCoreApplication.instance().processEvents()`.
- Verify signals were delivered and commands were written to `FakeSerial.written_bytes` with trailing `\n`.
- Verify `FakeSerial.close()` was executed.

#### Suite 4: Port Connection Failure Handling (`TestSerialWorkerConnectionFailures`)
- Mock `serial.Serial` raising `serial.SerialException("Device not found")`.
- Verify `error_received` is emitted with port details, and the thread terminates cleanly without hanging.

---

## 6. Proposed Code Changes for Implementer

Below is the concrete implementation proposed for `modules/serial_comm.py`:

```python
"""
Serial Communication module.

Runs a dedicated QThread that owns the serial port.
All commands are queued through a thread-safe queue.
Incoming data is parsed and emitted as Qt signals.

Signals
-------
data_received(float, float, int)  – (torque_nm, speed_rpm, dac_raw)
pid_received(float, float, float) – (kp, ki, kd)
pong_received()                   – PONG received
speed_received(int)               – raw ADC / speed count (backward compat)
torque_received(float)            – measured torque (convenience)
dac_received(int)                 – dac value (convenience)
ack_received(str)                 – acknowledged command string
error_received(str)               – error message text
connected()                       – port opened successfully
disconnected()                    – port closed
ready()                           – Arduino sent DYNO_READY

Protocol (see dyno_controller.ino):
    PC  → Arduino : "START\n", "STOP\n", "RESET\n", "PING\n",
                    "<GET_PID>\n", "<SET_PID:p,i,d>\n", "<SET_TORQUE:t>\n"
    Arduino → PC  : "<DATA:t,s,d>\n", "<PID_VALS:p,i,d>\n", "ACK:<cmd>\n",
                    "DYNO_READY\n", "PONG\n", "ERR:<msg>\n"
"""

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

    # Primary telemetry & tuning signals (Phase 2)
    data_received   = pyqtSignal(float, float, int)       # torque (N·m), speed, dac (0-4095)
    pid_received    = pyqtSignal(float, float, float)     # Kp, Ki, Kd
    pong_received   = pyqtSignal()                        # PONG response

    # Operational signals
    ack_received    = pyqtSignal(str)                     # acknowledged command text
    error_received  = pyqtSignal(str)                     # error text
    connected       = pyqtSignal()
    disconnected    = pyqtSignal()
    ready           = pyqtSignal()                        # DYNO_READY received

    # Backward-compatible & convenience signals
    speed_received  = pyqtSignal(int)                     # raw speed / ADC (0-1023)
    torque_received = pyqtSignal(float)                   # measured torque (N·m)
    dac_received    = pyqtSignal(int)                     # current DAC output

    def __init__(
        self,
        port: str,
        parent=None,
        boot_delay: float = 2.0,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._boot_delay = boot_delay
        self._serial_factory = serial_factory or serial.Serial
        self._serial: serial.Serial | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False

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
        self.send_command(f"<SET_TORQUE:{torque_nm:.2f}>")

    def stop(self) -> None:
        """Request the thread to exit gracefully."""
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._serial = self._serial_factory(
                self._port,
                baudrate=BAUD_RATE,
                timeout=READ_TIMEOUT,
                write_timeout=WRITE_TIMEOUT,
            )
        except (serial.SerialException, OSError) as exc:
            self.error_received.emit(f"Cannot open {self._port}: {exc}")
            return

        # Arduino resets on USB connect — give it time to boot
        if self._boot_delay > 0:
            time.sleep(self._boot_delay)
        if hasattr(self._serial, "reset_input_buffer"):
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
                    except (serial.SerialException, OSError) as exc:
                        self.error_received.emit(f"Write error: {exc}")
                        self._running = False
                        break

                # ---- Read incoming lines ----
                try:
                    raw = self._serial.readline()
                except (serial.SerialException, OSError) as exc:
                    self.error_received.emit(f"Read error: {exc}")
                    self._running = False
                    break

                if raw:
                    self._parse_line(raw.decode(errors="replace").strip())

        finally:
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

        # 1. Telemetry Packet: <DATA:t,s,d>
        if line.startswith("<DATA:") and line.endswith(">"):
            payload = line[6:-1]
            try:
                parts = payload.split(",")
                if len(parts) != 3:
                    raise ValueError("Expected 3 comma-separated fields")
                torque = float(parts[0].strip())
                speed = float(parts[1].strip())
                dac = int(parts[2].strip())

                self.data_received.emit(torque, speed, dac)
                self.speed_received.emit(int(round(speed)))
                self.torque_received.emit(torque)
                self.dac_received.emit(dac)
            except (ValueError, IndexError) as exc:
                self.error_received.emit(f"Malformed DATA frame: {line} ({exc})")

        # 2. PID Values Packet: <PID_VALS:p,i,d>
        elif line.startswith("<PID_VALS:") and line.endswith(">"):
            payload = line[10:-1]
            try:
                parts = payload.split(",")
                if len(parts) != 3:
                    raise ValueError("Expected 3 comma-separated fields")
                kp = float(parts[0].strip())
                ki = float(parts[1].strip())
                kd = float(parts[2].strip())

                self.pid_received.emit(kp, ki, kd)
            except (ValueError, IndexError) as exc:
                self.error_received.emit(f"Malformed PID_VALS frame: {line} ({exc})")

        # 3. Command Acknowledgments: ACK:...
        elif line.startswith("ACK:"):
            ack_msg = line[4:].strip()
            self.ack_received.emit(ack_msg)

        # 4. Link Heartbeat: PONG
        elif line == "PONG":
            self.ack_received.emit("PONG")
            self.pong_received.emit()

        # 5. Boot Notification: DYNO_READY
        elif line == "DYNO_READY":
            self.ready.emit()

        # 6. Firmware Errors: ERR:...
        elif line.startswith("ERR:"):
            self.error_received.emit(line[4:].strip())

        # 7. Legacy Speed Frame: SPEED:... (Backward Compatibility)
        elif line.startswith("SPEED:"):
            try:
                val = int(line[6:].strip())
                self.speed_received.emit(val)
                self.data_received.emit(0.0, float(val), 0)
            except ValueError:
                self.error_received.emit(f"Bad SPEED value: {line}")

        # Unrecognized lines are ignored safely
```
