# Original User Request

## 2026-09-28T13:17:53Z

<USER_REQUEST>
Implement Phase 2 of the dynamometer test bench software, focusing on updating the PC-side PyQt6 GUI to handle stability monitoring and PID UI integration with the newly developed closed-loop Arduino firmware.

Working directory: /home/doron/Links/GitHub Folder/motor-dyno-test-bench
Integrity mode: development

## Requirements

### R1. Update Serial Protocol (serial_comm.py)
Rewrite the serial parser to read `<DATA:t,s,d>` (torque, speed, dac) instead of the old `SPEED:x` format, and emit signals for all three values to the rest of the application. The Arduino also sends `<PID_VALS:p,i,d>`, `ACK:...`, `DYNO_READY`, and `PONG`.

### R2. Implement Stability Monitor (main_window.py)
Remove the open-loop "torque-to-DAC" math. Replace it with a Stability Monitor / Rolling Buffer. The software should not step to the next torque setpoint in the profile until the incoming `<DATA:...>` telemetry shows that the physical torque has settled at the target.

### R3. Wire PID UI to Serial Commands (pid_tuning_tab.py)
Connect the placeholder `print()` stubs in the PID Tuning tab to the actual serial commands to read and write PID values to the Arduino (`<GET_PID>` and `<SET_PID:p,i,d>`). 

## Acceptance Criteria

### Verification
- [ ] The `serial_comm.py` parser correctly matches and splits the `<DATA:t,s,d>` string format.
- [ ] The `main_window.py` control loop implements a stability delay or rolling average check before advancing to the next torque setpoint.
- [ ] The `pid_tuning_tab.py` correctly formats and transmits the `<SET_PID:p,i,d>` string.
</USER_REQUEST>
