# Implementation Plan: Phase 2 Dyno Test Bench

## Milestones Overview

### Milestone 1: Serial Protocol Overhaul (`modules/serial_comm.py`)
- Parse `<DATA:torque,speed,dac>` (floats and int).
- Parse `<PID_VALS:p,i,d>`.
- Parse `ACK:...`, `PONG`, `DYNO_READY`.
- Emit Qt signals: `data_received(float, float, int)`, `pid_received(float, float, float)`, `ack_received(str)`, `ready()`.
- Maintain clean backward compatibility for existing slots (`speed_received`).
- Verification: Unit tests for parsing, thread queueing, and signal emissions.

### Milestone 2: PID Tuning UI Integration (`gui/pid_tuning_tab.py`)
- Wire "Read from Arduino" to emit/dispatch `<GET_PID>`.
- Wire incoming `pid_received` to `set_stored_values(p, i, d)`.
- Wire "Save to Arduino" with input validation to emit/dispatch `<SET_PID:p,i,d>`.
- Wire "Update Software Parameters" to signal new tolerance and settling time.
- Wire status indicator (`STABLE` / `WAITING`).
- Verification: UI unit tests verifying signal emission, string formatting, and display update.

### Milestone 3: Stability Monitor & Closed-Loop Control Loop (`gui/main_window.py`)
- Implement a dedicated, clean `StabilityMonitor` (or rolling buffer helper) evaluating measured torque vs setpoint.
- Check that measured torque stays within ±tolerance% of target setpoint continuously for the full settling time.
- Remove open-loop torque-to-DAC calculation; replace with closed-loop `<SET_TORQUE:torque_nm>`.
- Gate profile advancement: do not advance to next setpoint until torque has stabilized.
- Feed stability state to `pid_tab.set_stability_status()`.
- Update live display and logger with actual measured torque, RPM, and DAC from telemetry.
- Verification: Test profile stepping under stable and fluctuating torque telemetry.

### Milestone 4: Full System E2E Integration & Verification
- Mock Arduino serial device simulating closed-loop firmware (`dyno_controller.ino`).
- Run complete profile test verifying:
  1. Serial protocol correctly exchanges telemetry and commands.
  2. Stability monitor prevents advancing setpoint until settling criteria met.
  3. PID tab reads and writes PID values accurately.
  4. Data logger captures authentic telemetry samples.
- Rigorous adversarial testing (Challenger) and forensic integrity audit (Auditor).
- Completion report to Sentinel.
