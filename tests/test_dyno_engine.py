"""
Unit and integration tests for DynoEngine, SerialTransport, and MockTransport.

Verifies:
  - MockTransport and SerialTransport functionality & protocol parsing.
  - Manual run lifecycle (start, setpoint change, stop, reset).
  - Profile run with stability gating and safety step timeout fallback.
  - Hybrid mode RPM threshold handoff between DAC and PID.
  - Hardware relays control and emergency / stop shutoff.
  - PID command transmission, gain validation, and ACK dispatch.
  - Torque calibration routine, peak ADC calculation, and auto-finish.
  - CSV logging and telemetry sampling.
  - Event hooks / callback firing.
  - Autonomous background control loop.
"""

import csv
import math
from pathlib import Path
import tempfile
import time
import unittest

from modules.calibration import CalibrationSettings
from modules.data_model import RunMode, RunState, Sample
from modules.engine import DynoEngine
from modules.plf import PiecewiseLinearFunction
from modules.stability_monitor import StabilityMonitor
from modules.transport import MockTransport, SerialTransport, list_serial_ports


class TestDynoTransport(unittest.TestCase):
    """Tests for pure Python transport implementations."""

    def test_mock_transport_lifecycle_and_helpers(self):
        transport = MockTransport()
        self.assertFalse(transport.is_connected)

        connected_called = False
        disconnected_called = False

        transport.on_connected = lambda: nonlocal_set("conn")
        transport.on_disconnected = lambda: nonlocal_set("disc")

        def nonlocal_set(val):
            nonlocal connected_called, disconnected_called
            if val == "conn":
                connected_called = True
            elif val == "disc":
                disconnected_called = True

        transport.connect("MOCK_PORT")
        self.assertTrue(transport.is_connected)
        self.assertTrue(connected_called)

        # Send helpers
        transport.send_start()
        transport.send_stop()
        transport.send_reset()
        transport.send_ping()
        transport.send_get_pid()
        transport.send_set_pid(12.3456, 7.891, 0.1234)
        transport.send_set_torque(2.55)
        transport.send_set_dac(2048)
        transport.send_relay("brake", True)

        expected = [
            "START",
            "STOP",
            "RESET",
            "PING",
            "<GET_PID>",
            "<SET_PID:12.3456,7.8910,0.1234>",
            "<SET_TORQUE:2.55>",
            "<SET_DAC:2048>",
            "<RELAY:BRAKE,1>",
        ]
        self.assertEqual(transport.sent_commands, expected)

        transport.disconnect()
        self.assertFalse(transport.is_connected)
        self.assertTrue(disconnected_called)

    def test_transport_parsing(self):
        transport = MockTransport()
        data_packets = []
        pid_packets = []
        acks = []
        errors = []
        ready_called = False

        transport.on_data = lambda t, s, d: data_packets.append((t, s, d))
        transport.on_pid = lambda p, i, d: pid_packets.append((p, i, d))
        transport.on_ack = lambda a: acks.append(a)
        transport.on_error = lambda e: errors.append(e)

        def mark_ready():
            nonlocal ready_called
            ready_called = True

        transport.on_ready = mark_ready

        # Valid packets
        transport.simulate_raw_line("<DATA:512.0,1000.0,2048>")
        self.assertEqual(len(data_packets), 1)
        self.assertEqual(data_packets[0], (512.0, 1000.0, 2048))

        transport.simulate_raw_line("<PID_VALS:50.0,5.0,0.5>")
        self.assertEqual(len(pid_packets), 1)
        self.assertEqual(pid_packets[0], (50.0, 5.0, 0.5))

        transport.simulate_raw_line("ACK:SET_TORQUE:2.5")
        self.assertEqual(acks, ["SET_TORQUE:2.5"])

        transport.simulate_raw_line("PONG")
        self.assertEqual(acks[-1], "PONG")

        transport.simulate_raw_line("DYNO_READY")
        self.assertTrue(ready_called)

        # Legacy SPEED frame
        transport.simulate_raw_line("SPEED:1200")
        self.assertEqual(data_packets[-1], (0.0, 1200.0, 0))

        # Malformed lines
        transport.simulate_raw_line("<DATA:bad,frame>")
        self.assertTrue(len(errors) > 0)
        transport.simulate_raw_line("<DATA:512.0,1000.0,2048")  # missing >
        self.assertTrue(len(errors) > 1)
        transport.simulate_raw_line("<PID_VALS:1,2>")
        self.assertTrue(len(errors) > 2)
        transport.simulate_raw_line("ERR:Hardware failure")
        self.assertIn("Hardware failure", errors)
        transport.simulate_raw_line("DAC_INIT_ERR:0x4")
        self.assertIn("DAC_INIT_ERR:0x4", errors)

    def test_list_serial_ports(self):
        ports = list_serial_ports()
        self.assertIsInstance(ports, list)


class TestDynoEngine(unittest.TestCase):
    """Comprehensive test suite for DynoEngine."""

    def setUp(self):
        self.transport = MockTransport(port="MOCK_DEV")
        self.calibration = CalibrationSettings()
        self.stability_monitor = StabilityMonitor(tolerance_pct=2.0, settling_time_s=1.0)
        self.engine = DynoEngine(
            transport=self.transport,
            calibration=self.calibration,
            stability_monitor=self.stability_monitor,
            control_mode="hybrid",
            step_timeout_s=5.0,
        )
        self.engine.connect()

    def tearDown(self):
        if self.engine.state == RunState.RUNNING:
            self.engine.stop()
        self.engine.stop_loop()
        self.engine.disconnect()

    def test_initial_state(self):
        self.assertEqual(self.engine.state, RunState.IDLE)
        self.assertEqual(self.engine.mode, RunMode.NONE)
        self.assertEqual(self.engine.target_torque, 0.0)
        self.assertEqual(self.engine.current_torque, 0.0)
        self.assertEqual(self.engine.current_rpm, 0.0)
        self.assertEqual(self.engine.current_dac, 0)
        self.assertFalse(self.engine.is_stable)
        self.assertTrue(self.engine.is_connected)
        self.assertEqual(
            self.engine.relays,
            {"BRAKE": False, "SENSOR": False, "AUX": False},
        )
        self.assertEqual(self.engine.control_mode, "hybrid")

    def test_manual_run_lifecycle(self):
        states_observed = []
        self.engine.on_state_change = lambda s: states_observed.append(s)

        # 1. Start manual run
        self.engine.start_manual(target_torque=2.5, mode="closed_loop")
        self.assertEqual(self.engine.state, RunState.RUNNING)
        self.assertEqual(self.engine.mode, RunMode.MANUAL)
        self.assertEqual(self.engine.target_torque, 2.5)
        self.assertEqual(self.engine.control_mode, "closed_loop")
        self.assertIn("START", self.transport.sent_commands)
        self.assertIn("<SET_TORQUE:2.50>", self.transport.sent_commands)
        self.assertEqual(states_observed, [RunState.RUNNING])

        # 2. Update setpoint while running
        self.engine.set_manual_torque(3.8)
        self.assertEqual(self.engine.target_torque, 3.8)
        self.assertIn("<SET_TORQUE:3.80>", self.transport.sent_commands)

        # 3. Stop run
        self.engine.stop()
        self.assertEqual(self.engine.state, RunState.FINISHED)
        self.assertIn("STOP", self.transport.sent_commands)
        self.assertIn("<SET_DAC:0>", self.transport.sent_commands)
        self.assertEqual(states_observed, [RunState.RUNNING, RunState.FINISHED])

        # 4. Reset
        self.engine.reset()
        self.assertEqual(self.engine.state, RunState.IDLE)
        self.assertEqual(self.engine.mode, RunMode.NONE)
        self.assertEqual(self.engine.target_torque, 0.0)
        self.assertIn("RESET", self.transport.sent_commands)
        self.assertEqual(
            states_observed,
            [RunState.RUNNING, RunState.FINISHED, RunState.IDLE],
        )

    def test_hybrid_mode_rpm_handoff(self):
        self.engine.start_manual(target_torque=2.0, mode="hybrid")
        self.assertEqual(self.engine.control_mode, "hybrid")

        # Initially at 0 RPM -> open-loop DAC sent
        # With max_torque = 5.0, 2.0 N·m -> (2.0 / 5.0) * 4095 = 1638
        self.assertIn("<SET_DAC:1638>", self.transport.sent_commands)

        # Simulate motor spinning up: speed_adc = 100.0 -> RPM = 50.0 (> 1.0)
        self.transport.simulate_data(torque=512.0, speed_rpm=100.0, dac_raw=1638)
        self.engine.tick()

        # Should transition to closed-loop PID <SET_TORQUE:2.00>
        self.assertIn("<SET_TORQUE:2.00>", self.transport.sent_commands)

        # Simulate motor stall: speed_adc = 0.0 -> RPM = 0.0 (<= 1.0)
        self.transport.simulate_data(torque=512.0, speed_rpm=0.0, dac_raw=1638)
        self.engine.tick()

        # Should revert to open-loop DAC <SET_DAC:1638>
        # Verify the command was sent again after stall
        dac_cmds = [cmd for cmd in self.transport.sent_commands if cmd == "<SET_DAC:1638>"]
        self.assertGreaterEqual(len(dac_cmds), 2)

    def test_open_loop_and_closed_loop_modes(self):
        # Open loop mode
        self.engine.start_manual(target_torque=2.5, mode="open_loop")
        # 2.5 N·m -> 2048 DAC
        self.assertIn("<SET_DAC:2048>", self.transport.sent_commands)

        # RPM rises, but open loop remains open loop
        self.transport.simulate_data(torque=512.0, speed_rpm=100.0, dac_raw=2048)
        self.engine.tick()
        torque_cmds = [c for c in self.transport.sent_commands if c.startswith("<SET_TORQUE:")]
        self.assertEqual(len(torque_cmds), 0)
        self.engine.stop()

        # Closed loop mode
        self.transport.sent_commands.clear()
        self.engine.start_manual(target_torque=1.5, mode="closed_loop")
        self.assertIn("<SET_TORQUE:1.50>", self.transport.sent_commands)
        self.engine.stop()

    def test_profile_run_with_stability_gating(self):
        # Create a 3-point test profile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("time_s,torque_nm\n")
            f.write("0.0,1.0\n")
            f.write("5.0,2.0\n")
            f.write("10.0,3.0\n")
            csv_path = Path(f.name)

        steps_recorded = []
        self.engine.on_step = lambda idx, t: steps_recorded.append((idx, t))

        # Start profile
        self.engine.start_profile(csv_path, mode="closed_loop")
        self.assertEqual(self.engine.state, RunState.RUNNING)
        self.assertEqual(self.engine.mode, RunMode.PROFILE)
        self.assertEqual(self.engine.current_step_idx, 0)
        self.assertEqual(self.engine.target_torque, 1.0)
        self.assertEqual(steps_recorded, [(0, 1.0)])
        self.assertIn("<SET_TORQUE:1.00>", self.transport.sent_commands)

        # Step 0: feed unstable telemetry -> step does NOT advance
        t_base = time.perf_counter()
        # 512 + 1.0 / torque_per_count for 1.0 N·m
        adc_1nm = 512.0 + 1.0 / self.calibration.torque_per_count
        adc_unstable = adc_1nm + 50.0  # off target

        self.transport.simulate_data(torque=adc_unstable, speed_rpm=50.0, dac_raw=1000)
        self.engine.tick(now=t_base + 0.1)
        self.assertEqual(self.engine.current_step_idx, 0)

        # Feed stable readings spanning > 1.0s (settling time)
        for i in range(12):
            now_t = t_base + 0.2 + (i * 0.1)
            self.stability_monitor.add_reading(1.0, timestamp=now_t)

        self.engine.tick(now=t_base + 1.5)
        # Should have stepped to step 1 (2.0 N·m)
        self.assertEqual(self.engine.current_step_idx, 1)
        self.assertEqual(self.engine.target_torque, 2.0)
        self.assertEqual(steps_recorded, [(0, 1.0), (1, 2.0)])
        self.assertIn("<SET_TORQUE:2.00>", self.transport.sent_commands)

        # Step 1: feed stable readings for 2.0 N·m
        t_base_2 = t_base + 2.0
        for i in range(12):
            now_t = t_base_2 + (i * 0.1)
            self.stability_monitor.add_reading(2.0, timestamp=now_t)

        self.engine.tick(now=t_base_2 + 1.5)
        # Should step to step 2 (3.0 N·m)
        self.assertEqual(self.engine.current_step_idx, 2)
        self.assertEqual(self.engine.target_torque, 3.0)
        self.assertEqual(steps_recorded, [(0, 1.0), (1, 2.0), (2, 3.0)])

        # Step 2: feed stable readings for 3.0 N·m -> Profile complete!
        t_base_3 = t_base_2 + 2.0
        for i in range(12):
            now_t = t_base_3 + (i * 0.1)
            self.stability_monitor.add_reading(3.0, timestamp=now_t)

        self.engine.tick(now=t_base_3 + 1.5)
        self.assertEqual(self.engine.state, RunState.FINISHED)
        self.assertIn("STOP", self.transport.sent_commands)

        csv_path.unlink(missing_ok=True)

    def test_profile_step_timeout_fallback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("time_s,torque_nm\n")
            f.write("0.0,1.0\n")
            f.write("5.0,2.0\n")
            csv_path = Path(f.name)

        self.engine.step_timeout_s = 2.0
        self.engine.start_profile(csv_path)
        self.assertEqual(self.engine.current_step_idx, 0)

        t0 = self.engine._step_start_time

        # Feed fluctuating telemetry (never stable)
        self.stability_monitor.add_reading(0.2, timestamp=t0 + 0.5)
        self.engine.tick(now=t0 + 1.0)
        self.assertEqual(self.engine.current_step_idx, 0)

        # Time advances beyond timeout (2.0s)
        self.stability_monitor.add_reading(0.2, timestamp=t0 + 2.5)
        self.engine.tick(now=t0 + 2.5)

        # Timeout should advance to step 1 (2.0 N·m)
        self.assertEqual(self.engine.current_step_idx, 1)
        self.assertEqual(self.engine.target_torque, 2.0)

        # Timeout on final step -> profile finishes
        t1 = self.engine._step_start_time
        self.engine.tick(now=t1 + 2.5)
        self.assertEqual(self.engine.state, RunState.FINISHED)

        csv_path.unlink(missing_ok=True)

    def test_hardware_relays_and_emergency_shutoff(self):
        relay_events = []
        self.engine.on_relay = lambda name, state: relay_events.append((name, state))

        # Turn on relays
        self.engine.set_relay("BRAKE", True)
        self.engine.set_relay("sensor", True)
        self.engine.set_relay("AUX", True)

        self.assertTrue(self.engine.relays["BRAKE"])
        self.assertTrue(self.engine.relays["SENSOR"])
        self.assertTrue(self.engine.relays["AUX"])

        self.assertIn("<RELAY:BRAKE,1>", self.transport.sent_commands)
        self.assertIn("<RELAY:SENSOR,1>", self.transport.sent_commands)
        self.assertIn("<RELAY:AUX,1>", self.transport.sent_commands)

        # Start a run
        self.engine.start_manual(1.0)
        self.assertEqual(self.engine.state, RunState.RUNNING)

        # Calling stop must turn off all relays and zero DAC
        self.engine.stop()
        self.assertEqual(self.engine.state, RunState.FINISHED)
        self.assertFalse(self.engine.relays["BRAKE"])
        self.assertFalse(self.engine.relays["SENSOR"])
        self.assertFalse(self.engine.relays["AUX"])

        self.assertIn("<RELAY:BRAKE,0>", self.transport.sent_commands)
        self.assertIn("<RELAY:SENSOR,0>", self.transport.sent_commands)
        self.assertIn("<RELAY:AUX,0>", self.transport.sent_commands)
        self.assertIn("<SET_DAC:0>", self.transport.sent_commands)

    def test_pid_tuning_and_eeprom(self):
        pid_received = []
        self.engine.on_pid = lambda p, i, d: pid_received.append((p, i, d))

        # 1. Read PID
        self.engine.get_pid()
        self.assertIn("<GET_PID>", self.transport.sent_commands)

        # Simulate response
        self.transport.simulate_pid(150.0, 12.5, 1.2)
        self.assertEqual(self.engine.stored_pid, (150.0, 12.5, 1.2))
        self.assertEqual(pid_received, [(150.0, 12.5, 1.2)])

        # 2. Write PID
        self.engine.set_pid(160.0, 15.0, 2.0)
        self.assertIn("<SET_PID:160.0000,15.0000,2.0000>", self.transport.sent_commands)

        # Invalid gains should raise ValueError
        with self.assertRaises(ValueError):
            self.engine.set_pid(-1.0, 10.0, 1.0)
        with self.assertRaises(ValueError):
            self.engine.set_pid(100.0, 2000.0, 1.0)
        with self.assertRaises(ValueError):
            self.engine.set_pid(float("nan"), 10.0, 1.0)

    def test_torque_calibration_routine(self):
        # 1. Start calibration
        self.engine.start_calibration()
        self.assertTrue(self.engine._is_calibrating)
        self.assertIn("START", self.transport.sent_commands)
        self.assertIn("<RELAY:SENSOR,1>", self.transport.sent_commands)
        self.assertIn("<SET_DAC:4095>", self.transport.sent_commands)

        # 2. Simulate force applied: peak ADC reaches 912.0
        self.transport.simulate_data(torque=700.0, speed_rpm=0.0, dac_raw=4095)
        self.transport.simulate_data(torque=912.0, speed_rpm=0.0, dac_raw=4095)
        self.transport.simulate_data(torque=850.0, speed_rpm=0.0, dac_raw=4095)

        # 3. Finish calibration
        success = self.engine.finish_calibration()
        self.assertTrue(success)
        self.assertFalse(self.engine._is_calibrating)
        self.assertIn("<SET_DAC:0>", self.transport.sent_commands)
        self.assertIn("<RELAY:SENSOR,0>", self.transport.sent_commands)
        self.assertIn("STOP", self.transport.sent_commands)

        # Check conversion factor: 5.0 / (912.0 - 512.0) = 5.0 / 400.0 = 0.0125
        self.assertAlmostEqual(self.calibration.torque_per_count, 0.0125, places=5)
        self.assertAlmostEqual(self.calibration.max_torque_nm, 5.0)

        # Test insufficient force (< 512.0)
        self.engine.start_calibration()
        self.transport.simulate_data(torque=480.0, speed_rpm=0.0, dac_raw=4095)
        fail = self.engine.finish_calibration()
        self.assertFalse(fail)
        self.assertAlmostEqual(self.calibration.torque_per_count, 0.0125, places=5)

    def test_telemetry_sampling_and_csv_logging(self):
        samples_received = []
        self.engine.on_telemetry = lambda s: samples_received.append(s)

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            log_path = Path(f.name)

        self.engine.start_logging(log_path)
        self.engine.start_manual(target_torque=1.5)

        # Feed telemetry and tick
        self.transport.simulate_data(torque=632.0, speed_rpm=100.0, dac_raw=1200)
        self.engine.tick()

        self.assertEqual(len(samples_received), 1)
        sample = samples_received[0]
        self.assertIsInstance(sample, Sample)
        self.assertEqual(sample.target_torque_nm, 1.5)
        self.assertEqual(sample.dac_raw, 1200)
        self.assertEqual(sample.rpm, 50.0)

        self.engine.stop()
        self.assertFalse(self.engine._logger.is_open())

        # Verify CSV content
        with log_path.open() as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["dac_raw"], "1200")
            self.assertEqual(rows[0]["rpm"], "50.00")

        log_path.unlink(missing_ok=True)

    def test_autonomous_background_loop(self):
        samples_received = []
        self.engine.on_telemetry = lambda s: samples_received.append(s)

        self.engine.start_loop(interval_s=0.01)
        self.engine.start_manual(target_torque=2.0)

        # Wait a short duration for the thread to tick
        time.sleep(0.08)

        self.engine.stop()
        self.engine.stop_loop()

        self.assertGreater(len(samples_received), 2)
        self.assertEqual(self.engine.session.sample_count(), len(samples_received))

    def test_multi_listener_registry(self):
        logs_1 = []
        logs_2 = []

        self.engine.add_listener("on_status", lambda msg: logs_1.append(msg))
        self.engine.add_listener("on_status", lambda msg: logs_2.append(msg))

        self.engine.set_relay("BRAKE", True)

        self.assertGreater(len(logs_1), 0)
        self.assertEqual(logs_1, logs_2)

        # Test remove_listener
        self.engine.remove_listener("on_status", lambda msg: None)  # non-existent
        listener_to_remove = lambda msg: None
        self.engine.add_listener("on_status", listener_to_remove)
        self.engine.remove_listener("on_status", listener_to_remove)

    def test_calibration_auto_finish_on_rpm(self):
        self.engine.start_calibration()
        self.assertTrue(self.engine._is_calibrating)

        # Apply peak force
        self.transport.simulate_data(torque=800.0, speed_rpm=0.0, dac_raw=4095)
        self.assertTrue(self.engine._is_calibrating)

        # Motor starts spinning (> 1.0 RPM) -> triggers auto-finish!
        self.transport.simulate_data(torque=800.0, speed_rpm=10.0, dac_raw=4095)
        self.assertFalse(self.engine._is_calibrating)
        self.assertIn("<SET_DAC:0>", self.transport.sent_commands)

    def test_disconnect_while_running_safely_stops(self):
        self.engine.start_manual(2.0)
        self.assertEqual(self.engine.state, RunState.RUNNING)

        # Simulate disconnect
        self.transport.disconnect()
        self.assertEqual(self.engine.state, RunState.FINISHED)
        self.assertFalse(self.engine.is_connected)

    def test_double_start_ignored(self):
        self.engine.start_manual(1.0)
        self.assertEqual(self.engine.target_torque, 1.0)
        # Second start while running is ignored
        self.engine.start_manual(3.0)
        self.assertEqual(self.engine.target_torque, 1.0)

    def test_profile_invalid_inputs(self):
        with self.assertRaises(FileNotFoundError):
            self.engine.start_profile("non_existent_file.csv")

        with self.assertRaises(TypeError):
            self.engine.start_profile(12345)

        empty_plf = PiecewiseLinearFunction()
        with self.assertRaises(ValueError):
            self.engine.start_profile(empty_plf)

    def test_callback_exception_safety(self):
        def buggy_callback(sample):
            raise RuntimeError("Bug in user callback")

        errors_caught = []
        self.engine.on_telemetry = buggy_callback
        self.engine.on_error = lambda err: errors_caught.append(err)

        self.engine.start_manual(1.0)
        self.engine.tick()

        # Engine should not crash, error reported
        self.assertGreater(len(errors_caught), 0)
        self.assertIn("Bug in user callback", errors_caught[0])

    def test_serial_transport_mocked_thread(self):
        class FakeSerial:
            def __init__(self, port, **kwargs):
                self.port = port
                self.is_open = True
                self.written = []
                self.lines = [b"<DATA:512.0,0.0,0>\n", b"DYNO_READY\n"]

            def write(self, data):
                self.written.append(data)

            def readline(self):
                if self.lines:
                    return self.lines.pop(0)
                time.sleep(0.01)
                return b""

            def reset_input_buffer(self):
                pass

            def close(self):
                self.is_open = False

        ready_called = False
        data_packets = []

        transport = SerialTransport(
            port="TEST_PORT",
            boot_delay=0.01,
            serial_factory=FakeSerial,
            on_data=lambda t, s, d: data_packets.append((t, s, d)),
            on_ready=lambda: nonlocal_ready(),
        )

        def nonlocal_ready():
            nonlocal ready_called
            ready_called = True

        transport.connect()
        # Wait a short moment for thread to process
        time.sleep(0.1)

        self.assertTrue(transport.is_connected)
        transport.send_command("PING")
        time.sleep(0.05)

        transport.disconnect()
        self.assertFalse(transport.is_connected)
        self.assertTrue(ready_called)
        self.assertEqual(len(data_packets), 1)
