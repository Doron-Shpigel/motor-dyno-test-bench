# Comprehensive Analysis: Requirement 3 (R3) — Wire PID UI to Serial Commands

**Author:** Explorer 2 (PID UI Explorer)  
**Date:** 2026-09-28  
**Scope:** `gui/pid_tuning_tab.py`, `gui/main_window.py`, `modules/serial_comm.py`, `arduino/dyno_controller/dyno_controller.ino`

---

## Executive Summary

This investigation analyzes the architecture, wiring, validation rules, and testing strategy for **Requirement 3 (R3)** of Phase 2: connecting the PID & Stability Tuning tab (`gui/pid_tuning_tab.py`) to the serial communication subsystem and stability monitor in `gui/main_window.py`.

Currently, `gui/pid_tuning_tab.py` contains UI widgets with placeholder `print()` stubs in action slots (`_on_read_from_arduino`, `_on_save_to_arduino`, `_on_update_software_params`), while `set_stored_values()` and `set_stability_status()` are implemented but disconnected in `gui/main_window.py`.

We establish:
1. A **clean signal-based architecture** matching `ControlPanel` that decouples `PidTuningTab` from serial connection lifecycles while maintaining an optional direct callback fallback.
2. A **strict yet practical input validation pipeline** for "Save to Arduino" ensuring valid non-negative floating-point numbers (`>= 0.0`), rejecting negative numbers, non-numeric strings, `NaN`, `Inf`, and values exceeding firmware safety limits (`1000.0`).
3. An exact **4-decimal string formatting contract** (`<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>`) perfectly matching the Arduino C++ tokenizer.
4. A **bidirectional telemetry and status update loop** routing `<PID_VALS:p,i,d>` to `set_stored_values()` and stability monitor outputs to the `STABLE` / `WAITING` badge.
5. A **headless PyQt6 unit testing strategy** utilizing Python standard library `unittest` and `PyQt6.QtTest.QTest` with `QT_QPA_PLATFORM=offscreen`.

---

## 1. Connecting "Read from Arduino" (`_on_read_from_arduino`)

### 1.1 Firmware Command & Response Contract
In `arduino/dyno_controller/dyno_controller.ino` (lines 182-187):
```cpp
else if (cmd.startsWith("<GET_PID>")) {
  Serial.print("<PID_VALS:");
  Serial.print(pid.Kp, 4); Serial.print(",");
  Serial.print(pid.Ki, 4); Serial.print(",");
  Serial.print(pid.Kd, 4); Serial.println(">");
}
```
The PC must send: `<GET_PID>\n`.
The Arduino responds with: `<PID_VALS:Kp,Ki,Kd>\n`.

### 1.2 Architectural Comparison: Signals vs Direct References

We evaluated three potential communication patterns for how `PidTuningTab` requests transmission:

| Criterion | Pattern A: Qt Signal (`sig_read_pid`) | Pattern B: Direct Worker/Sender Injection | Pattern C: Generic Command Signal (`sig_send_command`) |
| :--- | :--- | :--- | :--- |
| **Coupling** | **Zero** — purely event-driven | **High** — depends on worker instance | **Low** — depends on command strings |
| **Worker Lifecycle** | Immune to worker disconnect / reconnect | Risk of dangling / stale worker reference | Immune to worker lifecycle |
| **Consistency** | Matches `ControlPanel` (`sig_start`, `sig_stop`) | Inconsistent with existing GUI modules | Clean, but slightly less semantic |
| **Testability** | Trivially tested via signal receiver/spy | Requires mocking `SerialWorker` or callable | Trivially tested |

### 1.3 Recommended Pattern: Dual-Signal Emission with Optional Callback
To achieve maximum architectural flexibility and testability:
1. `PidTuningTab` declares semantic signals and generic command signals:
   ```python
   sig_read_pid = pyqtSignal()
   sig_send_command = pyqtSignal(str)
   ```
2. When the user clicks `_read_btn` (`_on_read_from_arduino`):
   ```python
   self.sig_read_pid.emit()
   self.sig_send_command.emit("<GET_PID>")
   if self._command_sender is not None:
       self._command_sender("<GET_PID>")
   ```
3. In `MainWindow`:
   `MainWindow` connects `self._pid_tab.sig_read_pid.connect(self._on_read_pid)`.
   In `_on_read_pid()`:
   ```python
   @pyqtSlot()
   def _on_read_pid(self) -> None:
       if self._worker and self._connected:
           self._worker.send_command("<GET_PID>")
           self._status("Reading PID parameters from Arduino...")
       else:
           self._status("Cannot read PID: Arduino is not connected.")
   ```

---

## 2. Updating Stored Values (`set_stored_values`)

### 2.1 Current Implementation in `gui/pid_tuning_tab.py`
Lines 262-266:
```python
def set_stored_values(self, kp: float, ki: float, kd: float) -> None:
    """Populate the read-only 'stored values' fields."""
    self._stored["kp"].setText(f"{kp:.4f}")
    self._stored["ki"].setText(f"{ki:.4f}")
    self._stored["kd"].setText(f"{kd:.4f}")
```
The internal dictionary `_stored` holds read-only `QLineEdit` widgets for `"kp"`, `"ki"`, and `"kd"`, formatted with 4 decimal places matching Arduino's firmware representation.

### 2.2 Telemetry Pipeline & Routing
1. **Arduino Serial Transmission**:
   Arduino emits `<PID_VALS:100.0000,10.0000,1.0000>\n`.
2. **Serial Worker Parser** (`modules/serial_comm.py`):
   In Milestone 1, `SerialWorker` parses `<PID_VALS:p,i,d>` and emits:
   ```python
   pid_received = pyqtSignal(float, float, float)
   ```
3. **MainWindow Routing** (`gui/main_window.py`):
   In `MainWindow._start_worker()`:
   ```python
   self._worker.pid_received.connect(self._on_pid_received)
   ```
   Slot in `MainWindow`:
   ```python
   @pyqtSlot(float, float, float)
   def _on_pid_received(self, kp: float, ki: float, kd: float) -> None:
       self._pid_tab.set_stored_values(kp, ki, kd)
       self._status(f"Arduino PID updated: Kp={kp:.4f}, Ki={ki:.4f}, Kd={kd:.4f}")
   ```
4. **Automatic Initial Read on Connect**:
   When the Arduino completes initialization, it transmits `DYNO_READY`. `SerialWorker` emits `ready`.
   In `MainWindow`:
   ```python
   self._worker.ready.connect(self._on_arduino_ready)

   def _on_arduino_ready(self) -> None:
       self._status("Arduino ready. Querying PID parameters...")
       self._worker.send_command("<GET_PID>")
   ```
   This automatically synchronizes the GUI stored values upon hardware connection without requiring manual user clicks.

### 2.3 Defensive Enhancements
- Guard against non-finite values (`math.isnan(kp)` or `math.isinf(kp)`): display `"ERR"`.
- Provide a getter method `get_stored_values() -> tuple[float | None, float | None, float | None]` to allow unit tests and higher-level monitors to verify displayed values programmatically.

---

## 3. Connecting "Save to Arduino" (`_on_save_to_arduino`)

### 3.1 Input Extraction
The editable input fields are stored in `self._inputs: dict[str, QLineEdit]` with keys `"kp"`, `"ki"`, `"kd"`.
Values are extracted as:
```python
text_kp = self._inputs["kp"].text().strip()
text_ki = self._inputs["ki"].text().strip()
text_kd = self._inputs["kd"].text().strip()
```

### 3.2 Input Validation Rules
A rigorous validation method `validate_inputs(self, allow_zero: bool = True) -> tuple[float, float, float] | None` must enforce:

1. **Non-Empty String Check**:
   Empty or whitespace-only inputs are rejected.
2. **Numeric Type Conversion**:
   Values must parse via `float(text)`. Non-numeric text (e.g. `"abc"`, `"1.2.3"`) raises `ValueError` and is rejected.
3. **Finite Float Check**:
   Python's `float("nan")` and `float("inf")` parse without raising `ValueError`. Therefore, `math.isnan(v)` and `math.isinf(v)` must be explicitly rejected.
4. **Sign & Zero Bounds**:
   - Negative values (`v < 0.0`) are **strictly prohibited** (in dyno brake control, negative gains invert feedback, causing catastrophic runaway acceleration).
   - Zero values (`v == 0.0`):
     - In control theory, operators commonly set `Ki = 0.0` (PD / P control) or `Kd = 0.0` (PI / P control).
     - Furthermore, `dyno_controller.ino` line 67 specifically allows `0.0` (`if (isnan(pid.Kp) || pid.Kp < 0 || pid.Kp > 1000)`).
     - Therefore, non-negative floats (`val >= 0.0`) are valid. If strictly positive (`val > 0.0`) is required for `Kp`, it can be enforced or parameterized.
5. **Firmware Safety Ceiling**:
   In `dyno_controller.ino`, gains exceeding `1000.0` are considered out-of-range memory corruption. The GUI should reject values `> 1000.0`.

### 3.3 String Formatting & Arduino C++ Compatibility
In `dyno_controller.ino` (lines 189-202):
```cpp
else if (cmd.startsWith("<SET_PID:")) {
  int startIdx = cmd.indexOf(':') + 1;
  int comma1 = cmd.indexOf(',', startIdx);
  int comma2 = cmd.indexOf(',', comma1 + 1);
  int endIdx = cmd.indexOf('>', comma2);

  pid.Kp = cmd.substring(startIdx, comma1).toFloat();
  pid.Ki = cmd.substring(comma1 + 1, comma2).toFloat();
  pid.Kd = cmd.substring(comma2 + 1, endIdx).toFloat();

  EEPROM.put(EEPROM_ADDR, pid); 
  errorIntegral = 0;
  Serial.println("ACK:SET_PID");
}
```
The exact command string must be:
```python
cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"
```
Example: `kp=120.5, ki=10.0, kd=1.2` formats as `<SET_PID:120.5000,10.0000,1.2000>`.
This guarantees exact comma indexing and tokenization in Arduino's `substring` logic.

### 3.4 Command Transmission & ACK Feedback
Upon successful validation:
1. Emit `sig_set_pid(kp, ki, kd)`
2. Emit `sig_send_command(cmd)`
3. Call `self._command_sender(cmd)` if defined.
4. When Arduino replies `ACK:SET_PID`:
   `MainWindow._on_ack_received("SET_PID")` can automatically query `<GET_PID>` to refresh the stored values display, confirming EEPROM write success to the user.

---

## 4. Connecting "Update Software Parameters" (`_on_update_software_params`)

### 4.1 UI Spinboxes
- `self._tolerance_spin`: `QDoubleSpinBox`
  - Range: `0.1 %` to `50.0 %`
  - Step: `0.5 %`
  - Default: `2.0 %`
- `self._settling_spin`: `QDoubleSpinBox`
  - Range: `0.1 s` to `60.0 s`
  - Step: `0.5 s`
  - Default: `1.5 s`

Note: The spinbox ranges are hardware-constrained by Qt, preventing out-of-range user entries.

### 4.2 Signal Definition & Wiring
Signal in `PidTuningTab`:
```python
sig_update_stability_params = pyqtSignal(float, float)  # (tolerance_pct, settling_time_s)
```
In `_on_update_software_params(self)`:
```python
@pyqtSlot()
def _on_update_software_params(self) -> None:
    tol = self._tolerance_spin.value()
    settle = self._settling_spin.value()
    self.sig_update_stability_params.emit(tol, settle)
```
In `MainWindow`:
```python
self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)

@pyqtSlot(float, float)
def _on_update_stability_params(self, tolerance_pct: float, settling_time_s: float) -> None:
    if hasattr(self, "_stability_monitor") and self._stability_monitor is not None:
        self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
    self._status(f"Stability parameters updated: ±{tolerance_pct:.1f}%, {settling_time_s:.1f}s")
```

### 4.3 Public Properties
Expose:
```python
@property
def tolerance(self) -> float:
    return self._tolerance_spin.value()

@property
def settling_time(self) -> float:
    return self._settling_spin.value()
```
This enables `MainWindow` to read initial stability settings on startup without duplicating magic numbers.

---

## 5. Status Display Verification (`set_stability_status`)

### 5.1 Badge Mechanics
In `gui/pid_tuning_tab.py` (lines 268-284):
- `stable=True`:
  - Text: `"STABLE"`
  - Background: `#1e4a2a` (forest green)
  - Text color: `#a6e3a1` (light green)
- `stable=False`:
  - Text: `"WAITING"`
  - Background: `#313244` (dark charcoal)
  - Text color: `#f9e2af` (amber)

### 5.2 Verification in Context
1. `MainWindow` evaluates stability on every control loop tick or telemetry event.
2. `MainWindow` calls `self._pid_tab.set_stability_status(is_stable)`.
3. When a test run is started, stopped, or reset: `MainWindow` resets stability and calls `self._pid_tab.set_stability_status(False)`.
4. Expose `is_stable(self) -> bool` property returning `self._status_label.text() == "STABLE"`.

---

## 6. Testing & Verification Strategy

### 6.1 Execution Environment & Constraints
- Python Environment: `/home/doron/Links/GitHub Folder/motor-dyno-test-bench/.env/bin/python`
- Environment Specs: Python 3.11, PyQt6 6.11.0, pyqtgraph 0.14.0, pyserial 3.5, numpy 2.4.6.
- `pytest` is not installed; the Python standard library `unittest` module is available.
- Headless execution requires `QT_QPA_PLATFORM=offscreen`.

### 6.2 Test Suite Architecture (`tests/test_pid_tuning_tab.py`)
Tests should exercise the complete user interaction and signal pipeline using `PyQt6.QtTest.QTest`:

```python
import sys
import unittest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from gui.pid_tuning_tab import PidTuningTab

app = QApplication.instance() or QApplication(sys.argv)

class TestPidTuningTab(unittest.TestCase):
    def setUp(self):
        self.tab = PidTuningTab()

    def test_default_values(self):
        self.assertEqual(self.tab._stored["kp"].text(), "—")
        self.assertEqual(self.tab.tolerance, 2.0)
        self.assertEqual(self.tab.settling_time, 1.5)
        self.assertFalse(self.tab.is_stable)

    def test_set_stored_values(self):
        self.tab.set_stored_values(120.5, 15.0, 2.5)
        self.assertEqual(self.tab._stored["kp"].text(), "120.5000")
        self.assertEqual(self.tab._stored["ki"].text(), "15.0000")
        self.assertEqual(self.tab._stored["kd"].text(), "2.5000")

    def test_stability_badge(self):
        self.tab.set_stability_status(True)
        self.assertTrue(self.tab.is_stable)
        self.assertEqual(self.tab._status_label.text(), "STABLE")
        self.tab.set_stability_status(False)
        self.assertFalse(self.tab.is_stable)
        self.assertEqual(self.tab._status_label.text(), "WAITING")

    def test_read_button_emits_signals(self):
        read_fired = []
        cmd_fired = []
        self.tab.sig_read_pid.connect(lambda: read_fired.append(True))
        self.tab.sig_send_command.connect(cmd_fired.append)

        QTest.mouseClick(self.tab._read_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(len(read_fired), 1)
        self.assertEqual(cmd_fired, ["<GET_PID>"])

    def test_save_valid_inputs(self):
        self.tab._inputs["kp"].setText("125.0")
        self.tab._inputs["ki"].setText("12.5")
        self.tab._inputs["kd"].setText("1.25")

        pid_emitted = []
        cmd_emitted = []
        self.tab.sig_set_pid.connect(lambda p, i, d: pid_emitted.append((p, i, d)))
        self.tab.sig_send_command.connect(cmd_emitted.append)

        QTest.mouseClick(self.tab._save_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(pid_emitted, [(125.0, 12.5, 1.25)])
        self.assertEqual(cmd_emitted, ["<SET_PID:125.0000,12.5000,1.2500>"])

    def test_save_invalid_inputs(self):
        invalid_cases = [
            ("-1.0", "1.0", "1.0"),   # negative Kp
            ("1.0", "-0.5", "1.0"),   # negative Ki
            ("abc", "1.0", "1.0"),    # non-numeric
            ("", "1.0", "1.0"),       # empty
            ("nan", "1.0", "1.0"),    # NaN
            ("1500.0", "1.0", "1.0"), # exceeds 1000
        ]
        for kp, ki, kd in invalid_cases:
            self.tab._inputs["kp"].setText(kp)
            self.tab._inputs["ki"].setText(ki)
            self.tab._inputs["kd"].setText(kd)
            emitted = []
            self.tab.sig_send_command.connect(emitted.append)
            QTest.mouseClick(self.tab._save_btn, Qt.MouseButton.LeftButton)
            self.assertEqual(emitted, [], f"Expected failure for case ({kp}, {ki}, {kd})")

    def test_update_software_parameters(self):
        self.tab._tolerance_spin.setValue(4.5)
        self.tab._settling_spin.setValue(3.0)

        params_emitted = []
        self.tab.sig_update_stability_params.connect(
            lambda tol, settle: params_emitted.append((tol, settle))
        )
        QTest.mouseClick(self.tab._update_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(params_emitted, [(4.5, 3.0)])
```

### 6.3 Verification Command
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_pid_tuning_tab.py
```
Execution takes < 0.1 seconds and requires no physical serial device or display.

---

## 7. Concrete Code Changes Proposal

### 7.1 Proposed Updates in `gui/pid_tuning_tab.py`

```python
<<<<
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
====
import math
from typing import Callable
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
>>>>
```

Add signals and state to `PidTuningTab`:
```python
class PidTuningTab(QWidget):
    """
    'PID & Stability Tuning' tab widget.
    """
    sig_read_pid = pyqtSignal()
    sig_set_pid = pyqtSignal(float, float, float)
    sig_send_command = pyqtSignal(str)
    sig_update_stability_params = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None, command_sender: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._command_sender = command_sender
        self._build_ui()
```

Implement validation and action slots:
```python
    def validate_inputs(self, allow_zero: bool = True) -> tuple[float, float, float] | None:
        """Validate user input fields for PID parameters."""
        raw_vals = {}
        for key in ("kp", "ki", "kd"):
            text = self._inputs[key].text().strip()
            if not text:
                return None
            try:
                val = float(text)
            except ValueError:
                return None
            if math.isnan(val) or math.isinf(val):
                return None
            if val < 0.0 or (not allow_zero and val == 0.0):
                return None
            if val > 1000.0:
                return None
            raw_vals[key] = val
        return (raw_vals["kp"], raw_vals["ki"], raw_vals["kd"])

    @pyqtSlot()
    def _on_read_from_arduino(self) -> None:
        self.sig_read_pid.emit()
        self.sig_send_command.emit("<GET_PID>")
        if self._command_sender:
            self._command_sender("<GET_PID>")

    @pyqtSlot()
    def _on_save_to_arduino(self) -> None:
        vals = self.validate_inputs()
        if vals is None:
            return
        kp, ki, kd = vals
        cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"
        self.sig_set_pid.emit(kp, ki, kd)
        self.sig_send_command.emit(cmd)
        if self._command_sender:
            self._command_sender(cmd)

    @pyqtSlot()
    def _on_update_software_params(self) -> None:
        tol = self._tolerance_spin.value()
        settle = self._settling_spin.value()
        self.sig_update_stability_params.emit(tol, settle)
```

Add helper properties:
```python
    @property
    def tolerance(self) -> float:
        return self._tolerance_spin.value()

    @property
    def settling_time(self) -> float:
        return self._settling_spin.value()

    @property
    def is_stable(self) -> bool:
        return self._status_label.text() == "STABLE"

    def get_stored_values(self) -> tuple[str, str, str]:
        return (self._stored["kp"].text(), self._stored["ki"].text(), self._stored["kd"].text())
```

### 7.2 Proposed Updates in `gui/main_window.py`

In `MainWindow._build_ui()`:
```python
self._pid_tab.sig_read_pid.connect(self._on_read_pid)
self._pid_tab.sig_set_pid.connect(self._on_set_pid)
self._pid_tab.sig_update_stability_params.connect(self._on_update_stability_params)
```

In `MainWindow._start_worker()`:
```python
self._worker.pid_received.connect(self._on_pid_received)
self._worker.ready.connect(lambda: self._worker.send_command("<GET_PID>"))
```

In `MainWindow` slots:
```python
@pyqtSlot()
def _on_read_pid(self) -> None:
    if self._worker and self._connected:
        self._worker.send_command("<GET_PID>")
        self._status("Querying PID parameters from Arduino...")
    else:
        self._status("Cannot read PID: Arduino not connected.")

@pyqtSlot(float, float, float)
def _on_set_pid(self, kp: float, ki: float, kd: float) -> None:
    cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"
    if self._worker and self._connected:
        self._worker.send_command(cmd)
        self._status(f"Sent: {cmd}")
    else:
        self._status("Cannot save PID: Arduino not connected.")

@pyqtSlot(float, float, float)
def _on_pid_received(self, kp: float, ki: float, kd: float) -> None:
    self._pid_tab.set_stored_values(kp, ki, kd)
    self._status(f"Received PID parameters: Kp={kp:.4f}, Ki={ki:.4f}, Kd={kd:.4f}")

@pyqtSlot(float, float)
def _on_update_stability_params(self, tolerance_pct: float, settling_time_s: float) -> None:
    if hasattr(self, "_stability_monitor") and self._stability_monitor is not None:
        self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
    self._status(f"Stability parameters updated: ±{tolerance_pct:.1f}%, {settling_time_s:.1f}s")
```

---

## 8. Conclusion

Requirement 3 provides the critical user-facing configuration bridge for both hardware closed-loop tuning and software stability detection. By decoupling the UI through Qt signals, enforcing robust input validation matching Arduino firmware safety specs, and providing headless unit testability with `unittest` and `QTest`, Phase 2 will achieve reliable, production-grade closed-loop dyno operation.
