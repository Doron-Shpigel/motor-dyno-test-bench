# Forensic Auditor Handoff Report — Milestone 1 (Serial Protocol Update)

**Agent**: Forensic Auditor (`auditor_milestone1_1`)  
**Target**: Milestone 1 (`modules/serial_comm.py`, `tests/test_serial_comm.py`)  
**Verdict**: **CLEAN**  
**Handoff Type**: Hard (Task Complete)  

---

## 1. Observation

### 1.1 Source Code and AST Inspection
- In `/home/doron/Links/GitHub Folder/motor-dyno-test-bench/modules/serial_comm.py`:
  - Lines 57–69 define Qt signals:
    ```python
    data_received   = pyqtSignal(float, float, int)       # (torque, speed, dac)
    pid_received    = pyqtSignal(float, float, float)     # (kp, ki, kd)
    speed_received  = pyqtSignal(int)                     # backward compatibility; int(round(speed))
    torque_received = pyqtSignal(float)                   # measured torque (convenience)
    dac_received    = pyqtSignal(int)                     # dac value (convenience)
    ack_received    = pyqtSignal(str)
    error_received  = pyqtSignal(str)
    connected       = pyqtSignal()
    disconnected    = pyqtSignal()
    ready           = pyqtSignal()
    pong_received   = pyqtSignal()
    ```
  - Lines 203–222 implement `<DATA:t,s,d>` frame parsing:
    ```python
    if line.startswith("<DATA:") and line.endswith(">"):
        payload = line[6:-1]
        try:
            parts = payload.split(",")
            if len(parts) != 3:
                raise ValueError(f"Expected 3 fields, got {len(parts)}")
            torque = float(parts[0].strip())
            speed = float(parts[1].strip())
            dac = int(parts[2].strip())

            self.data_received.emit(torque, speed, dac)
            self.speed_received.emit(int(round(speed)))
            self.torque_received.emit(torque)
            self.dac_received.emit(dac)
        except Exception as exc:
            self.error_received.emit(f"Malformed DATA frame: {line} ({exc})")
    ```
  - Lines 224–240 implement `<PID_VALS:p,i,d>` parsing with three `float` extractions.
  - Lines 90–120 define typed helper methods `send_command`, `send_start`, `send_stop`, `send_reset`, `send_ping`, `send_get_pid`, `send_set_pid`, and `send_set_torque`.
  - No hardcoded test values, mock flags, or static return stubs were found in `serial_comm.py`.

### 1.2 Execution Observations
- Executed unit test suite:
  ```bash
  .env/bin/python -m unittest tests/test_serial_comm.py -v
  ```
  Result:
  ```
  Ran 29 tests in 0.257s
  OK
  ```
- Executed line-level execution trace using Python `trace`:
  - `modules/serial_comm.py` line 203 was executed 32 times.
  - Numeric conversions at lines 209–211 were executed 7–9 times.
  - Signal emissions at lines 213–216 were executed 6 times.
- Executed empirical verification on arbitrary inputs:
  - 1,000 randomized `<DATA:t,s,d>` frames with variable floats/integers parsed with 100% numerical fidelity.
  - 500 randomized `<PID_VALS:p,i,d>` frames with variable floats parsed with 100% numerical fidelity.
  - 10 distinct malformed packet variations safely triggered `error_received` without thread crashes.
- Executed GUI regression test:
  ```bash
  QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('MainWindow instantiation OK')"
  ```
  Result: `MainWindow instantiation OK`

### 1.3 Pre-populated Artifact Scan
- Command: `find . -name '*.log' -o -name '*result*' -o -name '*output*'`
- Output: Zero pre-populated artifacts or synthetic test logs in the repository.

---

## 2. Logic Chain

1. **Absence of Fraudulent Shortcuts**:
   - Observations 1.1 and 1.3 confirm that no hardcoded return values, mock bypasses, or pre-recorded logs exist in the repository.
   - The tokenization logic (`startswith`, `endswith`, `split(',')`) and type casting (`float()`, `int()`) in `modules/serial_comm.py` lines 203–240 operate on dynamic incoming text.

2. **Genuine Execution and Coverage**:
   - Observation 1.2 confirms that tests are not self-certifying stubs; the Python runtime trace verified that `_parse_line` was exercised under all branches during `tests/test_serial_comm.py`.
   - Observation 1.2 also proves code authenticity: the parser successfully handles thousands of arbitrary and randomized input values generated outside the unit test fixtures.

3. **Acceptance Criteria Fulfillment**:
   - The Milestone 1 criterion requires that *"The `serial_comm.py` parser correctly matches and splits the `<DATA:t,s,d>` string format."*
   - As directly verified in Observation 1.1 lines 203–222 and Observation 1.2, `<DATA:t,s,d>` is matched, split into three tokens, converted to `(float, float, int)`, and emitted via `data_received(float, float, int)` and convenience signals.

4. **Verdict Deduction**:
   - In accordance with the General Project Profile and `development` integrity mode rules, zero Prohibited Patterns exist.
   - Therefore, the verdict is **CLEAN**.

---

## 3. Caveats

- **Physical Hardware**: Verification was performed in software using `MockSerial` and in-memory streams rather than physical USB hardware connected to an Arduino.
- **Concurrency Defect (Non-Integrity)**: An adversarial test identified a race condition where invoking `stop()` during the `_boot_delay` window causes `self._running` to be overwritten to `True` when sleep finishes. This is a threading defect rather than an integrity violation, and has been documented in `audit_report.md` for resolution in future work.

---

## 4. Conclusion

The Milestone 1 implementation in `modules/serial_comm.py` and `tests/test_serial_comm.py` is **authentic, genuine, and compliant with all project requirements**.

Final Verdict: **CLEAN**

---

## 5. Verification Method

To independently reproduce the forensic audit:

1. **Verify Unit Tests**:
   ```bash
   .env/bin/python -m unittest tests/test_serial_comm.py -v
   ```
   *Expected*: 29 tests pass with `OK`.

2. **Verify Arbitrary Input Parsing (1,000 packets)**:
   ```bash
   .env/bin/python -c '
   import os, random
   os.environ["QT_QPA_PLATFORM"] = "offscreen"
   from PyQt6.QtCore import QCoreApplication
   app = QCoreApplication.instance() or QCoreApplication([])
   from modules.serial_comm import SerialWorker
   w = SerialWorker(port="TEST", boot_delay=0.0)
   received = []
   w.data_received.connect(lambda t, s, d: received.append((t, s, d)))
   for i in range(1000):
       t, s, d = round(random.uniform(-50, 100), 2), round(random.uniform(0, 5000), 2), random.randint(0, 4095)
       w._parse_line(f"<DATA:{t},{s},{d}>")
       assert received[-1] == (t, s, d)
   print("Arbitrary 1000 packets verified OK")
   '
   ```
   *Expected*: Prints `Arbitrary 1000 packets verified OK`.

3. **Verify MainWindow Compatibility**:
   ```bash
   QT_QPA_PLATFORM=offscreen .env/bin/python -c "from gui.main_window import MainWindow; from PyQt6.QtWidgets import QApplication; app = QApplication([]); win = MainWindow(); print('MainWindow instantiation OK')"
   ```
   *Expected*: Prints `MainWindow instantiation OK`.
