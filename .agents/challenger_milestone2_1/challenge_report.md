# Empirical Challenge Report: Milestone 2 PID Tuning UI Input Validation & Command Formatting

**Target**: `gui/pid_tuning_tab.py` (`validate_inputs`, `_on_save_to_arduino`, `set_stored_values`, software parameters)  
**Agent**: Challenger 1 (Milestone 2)  
**Date**: 2026-09-28  
**Verdict**: **CONFIRMED** (Core validation & headless error handling robust; 2 subtle boundary edge cases identified for hardening)

---

## 1. Executive Summary

We conducted adversarial stress testing against the newly wired PID tuning GUI component (`gui/pid_tuning_tab.py`). The objective was to verify whether malicious strings, delimiter/command injection attacks, extreme numerical values, NaN/Inf variations, or formatting edge cases could bypass input validation or produce malformed serial commands targeting the Arduino firmware (`<SET_PID:...>`). Furthermore, we verified that error handling operates in a completely non-blocking manner suitable for headless test and CI environments.

A dedicated 16-case empirical test harness (`tests/test_adversarial_pid_tuning.py`) and generator fuzzing suite were constructed and executed using `.env/bin/python`.

### Key Outcomes
- **Invalid Inputs Never Produce Malformed Commands**: **CONFIRMED**. In 100% of tested failure cases (100+ injection, non-numeric, and out-of-range inputs), validation cleanly rejected the input, returned `None`, and prevented signal emission (`sig_set_pid`, `sig_send_command`) and callback invocation.
- **Headless Non-Blocking Error Handling**: **CONFIRMED**. The GUI uses inline feedback labels (`_feedback_label`) without spawning blocking modal dialogs (`QMessageBox`). `QApplication.activeModalWidget()` remained `None` in all test cycles.
- **Two Minor Edge Cases Identified**:
  1. Signed negative zero (`"-0.0"`) bypasses `val < 0.0` (as `-0.0 < 0.0` is `False` in IEEE 754) and serializes to `<SET_PID:-0.0000,0.0000,0.0000>`.
  2. Sub-resolution positive floats (`0.0 < val < 0.00005`, e.g. `0.00004` or `1e-5`) pass `allow_zero=False` validation but round to `"0.0000"` under 4-decimal serialization.

---

## 2. Challenge Dimensions & Test Results

### Challenge 1: Embedded Delimiters and Protocol / Command Injection
- **Assumption Challenged**: User inputs containing commas, brackets, newlines, semicolons, shell metacharacters, or protocol frames could reach the serial output channel.
- **Attack Vectors Tested**:
  - Embedded commas: `"1.0,2.0"`, `",1.0"`, `"1.0,"`, `",,,,"`
  - Embedded brackets & XML/HTML: `"<script>"`, `"<script>alert(1)</script>"`, `"1.0>evil"`, `"1.0> <SET_PID:0,0,0>"`
  - Protocol frame injection: `"<SET_PID:1.0,1.0,1.0>"`, `"<SET_TORQUE:5000>"`
  - CRLF injection: `"1.0\r\nSTART"`, `"1.0\nSTOP"`, `"1.0\rRESET"`, `"1.0\n<SET_PID:0,0,0>"`
  - Command separators: `"1.0;PING"`, `"1.0&START"`, `"1.0|STOP"`
  - Binary & null bytes: `"1.0\x00evil"`, `"\x00"`, `"\x01\x02\x03"`
- **Result**: **PASS**. Python's `float(text.strip())` requires the entire string to be a valid numeric literal. All delimiters, tags, and injection payloads raised `ValueError`, which was caught and routed to inline error feedback. No signals were emitted.

### Challenge 2: Non-Finite Values (NaN, Inf, Overflow Exponents)
- **Assumption Challenged**: Floating-point parsing might allow non-finite values into EEPROM or mathematical calculations.
- **Attack Vectors Tested**:
  - `nan`, `NaN`, `NAN`, `+nan`, `-nan`, `+NaN`, `-NaN`
  - `inf`, `Inf`, `INF`, `+inf`, `-inf`, `+Inf`, `-Inf`
  - `infinity`, `Infinity`, `INFINITY`, `+infinity`, `-infinity`
  - Overflows: `1e309`, `-1e309`, `1e1000`, `-1e1000`
- **Result**: **PASS**. In all cases, `math.isfinite(val)` evaluated to `False`. Validation returned `None`, set `self.last_error = "Field ... must be finite."`, and blocked command generation.

### Challenge 3: Negative Values & Numerical Boundaries
- **Assumption Challenged**: Negative PID gains (which would create destabilizing positive feedback in the control loop) or values exceeding the 1000.0 safety limit could be sent to Arduino.
- **Attack Vectors Tested**:
  - Small negatives: `-0.001`, `-0.0001`, `-1e-5`, `-1e-10`, `-1e-300`
  - Large negatives: `-1.0`, `-10.0`, `-100.0`, `-1000.0`, `-1e300`
  - Upper boundary excess: `1000.0001`, `1000.01`, `1000.1`, `1001.0`, `1e4`, `1e300`
- **Result**: **PASS**. All negative values and excess values were rejected with descriptive inline error messages. Boundary value `1000.0` was cleanly accepted.

### Challenge 4: Signed Negative Zero (`"-0.0"`) Edge Case
- **Assumption Challenged**: Input validation guarantees all accepted values are non-negative (`>= 0.0`).
- **Attack Scenario**: User inputs `"-0.0"`, `"-0"`, or `"-0.00"`.
- **Empirical Observation**:
  - `float("-0.0")` evaluates to `-0.0`.
  - In IEEE 754, `-0.0 < 0.0` is `False`.
  - Consequently, `if val < 0.0:` does not trigger.
  - When `allow_zero=True` (default in `_on_save_to_arduino`), `validate_inputs` returns `(-0.0, 0.0, 0.0)`.
  - Formatting with `f"{kp:.4f}"` outputs `"-0.0000"`.
  - Emitted command is `<SET_PID:-0.0000,0.0000,0.0000>`.
- **Blast Radius**: Low. In Arduino AVR/SAMD firmware, `"-0.0000".toFloat()` yields `-0.0`, and `-0.0 < 0` is false. However, an explicit negative sign is transmitted over serial and stored with sign-bit 1 in EEPROM.
- **Mitigation Recommendation**: In `validate_inputs()`, normalize zero:
  ```python
  if val == 0.0:
      val = 0.0  # Clears signed negative zero to +0.0
  ```
  or reject signed negative zero via `math.copysign(1.0, val) < 0`.

### Challenge 5: Sub-Resolution Underflow with `allow_zero=False`
- **Assumption Challenged**: Setting `allow_zero=False` guarantees that non-zero gains will be sent to the Arduino.
- **Attack Scenario**: User inputs `0.00004` or `1e-5` when `allow_zero=False`.
- **Empirical Observation**:
  - `val = 0.00004` is not equal to `0.0`, so `if not allow_zero and val == 0.0:` does not trigger.
  - Validation passes and returns `(0.00004, ...)`.
  - When formatted with `:.4f`, `0.00004` rounds to `0.0000`.
  - Command sent to Arduino is `<SET_PID:0.0000,0.0000,0.0000>`, transmitting zero gains despite `allow_zero=False`.
- **Blast Radius**: Low. `allow_zero=False` is currently only used in unit tests and not in `_on_save_to_arduino` (which allows zero for PI/PD configurations).
- **Mitigation Recommendation**: If strict positive values are required, check `if not allow_zero and round(val, 4) <= 0.0:`.

### Challenge 6: Non-Blocking Error Handling in Headless / CI Mode
- **Assumption Challenged**: Validation failure might spawn a modal dialog (`QMessageBox`) or raise unhandled exceptions that block headless execution.
- **Test Harness**:
  - Executed under `QT_QPA_PLATFORM=offscreen`.
  - Tested invalid submissions while querying `QApplication.activeModalWidget()`.
  - Measured response execution latency across invalid inputs.
- **Result**: **PASS**. Latency was < 1ms. `activeModalWidget()` was `None` in every case. Error messages were cleanly rendered in `self._feedback_label` and readable via `self.last_error`.

### Challenge 7: Unicode & Internationalization
- **Assumption Challenged**: Non-ASCII or Unicode characters could corrupt serial framing.
- **Attack Vectors Tested**:
  - Non-ASCII punctuation and text: `1.0🚀`, `π`, `1.0α`, `1.0а` (Cyrillic), `1،5` (Arabic comma), `1,5` (European decimal).
  - Zero-width characters: `\u200b` (zero-width space), `\ufeff` (BOM).
  - Unicode numerals: `１２.５` (fullwidth digits), `١٢.٥` (Arabic-Indic numerals).
- **Result**: **PASS**. Non-numeric Unicode raised `ValueError` and was rejected. Unicode numerals were converted to standard floats by Python and serialized into strictly ASCII characters (`isascii() == True`).

### Challenge 8: Generator Fuzzing & Rapid Re-entrancy
- **Assumption Challenged**: Rapid user interactions or complex corrupted input sequences could cause race conditions or state corruption.
- **Test Harness**:
  - Fuzzed `validate_inputs` with 200 varied corrupt payloads.
  - Executed 100 alternating rapid clicks between `_read_btn` and `_save_btn`.
- **Result**: **PASS**. All 100 commands queued in exact sequence; no state leak or crash.

---

## 3. Stress Test Summary Matrix

| Test Case | Scenario / Input | Expected Behavior | Actual Behavior | Verdict |
|---|---|---|---|---|
| `test_embedded_delimiters` | `1.0,2.0`, `<script>`, `1.0>evil`, CRLF | Rejected, no signals | Rejected, no signals | **PASS** |
| `test_nan_and_inf` | `nan`, `inf`, `-inf`, `1e309`, `1e1000` | Rejected by `isfinite` | Rejected by `isfinite` | **PASS** |
| `test_negative_values` | `-0.001`, `-10.0`, `-1e300` | Rejected `< 0.0` | Rejected `< 0.0` | **PASS** |
| `test_signed_negative_zero` | `"-0.0"`, `"-0"` | Edge case probe | Accepted, sends `-0.0000` | **BORDER FINDING** |
| `test_sub_resolution_underflow` | `0.00004` with `allow_zero=False` | Edge case probe | Formats to `0.0000` | **BORDER FINDING** |
| `test_scientific_exponents` | `1e2`, `1e3` vs `1e4`, `1e300` | In-bounds pass, excess rejected | In-bounds pass, excess rejected | **PASS** |
| `test_headless_non_blocking` | Offscreen error validation | No modal dialog, <100ms | No modal dialog, 0.3ms | **PASS** |
| `test_command_formatting_regex` | Valid float combinations | Strictly matches `<SET_PID:...>` | Strictly matches `<SET_PID:...>` | **PASS** |
| `test_missing_fields` | `del _inputs["ki"]` | Graceful error, no crash | Handled gracefully | **PASS** |
| `test_set_stored_values` | NaN / Inf in stored values | Displays `"ERR"` | Displays `"ERR"` | **PASS** |
| `test_spinbox_clamping` | Programmatic -10, 100 to spinboxes | Clamped to [0.1, 50/60] | Clamped correctly | **PASS** |
| `test_fuzz_random_garbage` | 200 fuzzed corrupt inputs | Invariant maintained | Invariant maintained | **PASS** |

---

## 4. Overall Verification Command & Coverage

Verification executed via:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest tests/test_adversarial_pid_tuning.py -v
```
**Result**: 16/16 tests passed in 0.118s.

Full suite regression executed via:
```bash
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover tests -v
```
**Result**: 140/140 tests passed in 9.005s, 0 failures, 0 errors.

---

## 5. Final Verdict

**VERDICT: CONFIRMED**

The input validation and command formatting implementation in `gui/pid_tuning_tab.py` is solid, safe against delimiter and command injection attacks, robust against non-finite float vulnerabilities, and non-blocking in headless environments. The two minor edge cases noted above represent optional defense-in-depth hardening opportunities.
