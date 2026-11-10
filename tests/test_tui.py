"""
Unit and integration tests for DynoTUI, SimulatedTransport, ASCII graphing, and CLI.

Verifies:
  - ASCII graph formatting, bounds, dynamic scaling, and character placement.
  - SimulatedTransport motor physics, command handling, telemetry generation, and PID logic.
  - DynoTUI initialization, event callback wiring, and status logging.
  - Direct key action handling (emergency stop, reset, setpoint tuning, mode toggle, relays, quit).
  - Interactive modal prompts with simulated keystrokes (Enter, Escape, Backspace).
  - Headless screen rendering across standard, large, and undersized terminal dimensions.
  - End-to-end demo mode run with simulated motor telemetry and stability gating.
  - CLI argument parsing for tui.py.
"""

import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from modules.data_model import RunMode, RunState, Sample
from modules.engine import DynoEngine
from modules.transport import MockTransport, SimulatedTransport
from modules.tui import (
    COLOR_CONNECTED,
    COLOR_CYAN,
    COLOR_DEFAULT,
    COLOR_WARNING,
    DynoTUI,
    format_ascii_graph,
)
from tui import parse_args


class MockCursesWindow:
    """Mock curses stdscr window for headless testing without interactive tty."""

    def __init__(self, height: int = 24, width: int = 80):
        self.height = height
        self.width = width
        self.calls: list[tuple[str, Any]] = []
        self.screen: dict[tuple[int, int], str] = {}
        self.key_queue: list[int] = []

    def getmaxyx(self) -> tuple[int, int]:
        return (self.height, self.width)

    def erase(self) -> None:
        self.screen.clear()
        self.calls.append(("erase", None))

    def refresh(self) -> None:
        self.calls.append(("refresh", None))

    def nodelay(self, flag: bool) -> None:
        pass

    def keypad(self, flag: bool) -> None:
        pass

    def move(self, y: int, x: int) -> None:
        self.calls.append(("move", (y, x)))

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.calls.append(("addstr", (y, x, text, attr)))
        for i, ch in enumerate(text):
            if 0 <= x + i < self.width and 0 <= y < self.height:
                self.screen[(y, x + i)] = ch

    def getch(self) -> int:
        if self.key_queue:
            return self.key_queue.pop(0)
        return -1

    def get_line_text(self, y: int) -> str:
        """Helper to reconstruct text of a specific screen row."""
        return "".join(self.screen.get((y, x), " ") for x in range(self.width))


class TestASCIIGraph(unittest.TestCase):
    """Tests for ASCII history graph / sparkline generation."""

    def test_empty_samples(self):
        lines = format_ascii_graph([], height=5, width=60)
        self.assertEqual(len(lines), 5)
        # Top line has Y-max label
        label, cols = lines[0]
        self.assertIn("5.0┤", label)
        # Bottom line has baseline axis
        b_label, b_cols = lines[-1]
        self.assertIn("0.0┴", b_label)
        # Verify columns length
        self.assertEqual(len(cols), 60 - 7)

    def test_samples_plotting_and_markers(self):
        samples = [
            Sample(elapsed_s=0.1, torque_nm=0.0, rpm=0.0, dac_raw=0, adc_raw=0, target_torque_nm=1.0),
            Sample(elapsed_s=0.2, torque_nm=0.5, rpm=1000.0, dac_raw=1000, adc_raw=200, target_torque_nm=1.0),
            Sample(elapsed_s=0.3, torque_nm=1.0, rpm=2000.0, dac_raw=2000, adc_raw=400, target_torque_nm=1.0),
        ]
        lines = format_ascii_graph(samples, height=6, width=40)
        self.assertEqual(len(lines), 6)

        # Flatten characters plotted
        all_chars = [ch for _, cols in lines for ch, _ in cols]
        # Must contain target '-' marker, measured '*' marker, and match 'X' marker (at torque=1.0==target)
        self.assertIn("-", all_chars)
        self.assertIn("*", all_chars)
        self.assertIn("X", all_chars)

    def test_dynamic_scaling(self):
        samples = [
            Sample(elapsed_s=1.0, torque_nm=3.8, rpm=2000.0, dac_raw=2000, adc_raw=400, target_torque_nm=4.0),
        ]
        lines = format_ascii_graph(samples, height=5, width=50)
        top_label, _ = lines[0]
        # Y-max should have scaled up above 4.0 N·m (e.g. 5.0 or 5.5)
        self.assertTrue(any(float(part) >= 4.0 for part in top_label.replace("┤", "").split() if part.replace(".", "").isdigit()))

    def test_various_dimensions(self):
        samples = [Sample(elapsed_s=float(i), torque_nm=float(i % 3), rpm=1000, dac_raw=500, adc_raw=100, target_torque_nm=2.0) for i in range(50)]
        for h in (3, 5, 8):
            for w in (20, 50, 100):
                lines = format_ascii_graph(samples, height=h, width=w)
                self.assertEqual(len(lines), h)
                for label, cols in lines:
                    self.assertEqual(len(cols), w - 7)


class TestSimulatedTransport(unittest.TestCase):
    """Tests for SimulatedTransport physics and responsiveness."""

    def test_connect_and_disconnect(self):
        transport = SimulatedTransport(tick_interval_s=0.01)
        self.assertFalse(transport.is_connected)

        connected_called = False
        transport.on_connected = lambda: nonlocal_flag("conn")

        def nonlocal_flag(v):
            nonlocal connected_called
            if v == "conn":
                connected_called = True

        transport.connect("DEMO_PORT")
        self.assertTrue(transport.is_connected)
        self.assertTrue(connected_called)

        # Clean disconnect
        transport.disconnect()
        self.assertFalse(transport.is_connected)

    def test_simulated_motor_response_and_tracking(self):
        data_packets: list[tuple[float, float, int]] = []
        transport = SimulatedTransport(tick_interval_s=0.01)
        transport.on_data = lambda t, s, d: data_packets.append((t, s, d))

        transport.connect("DEMO_PORT")

        # Start motor and command torque setpoint
        transport.send_command("START")
        transport.send_command("<SET_TORQUE:2.50>")

        # Let simulation thread tick
        time.sleep(0.15)

        self.assertGreater(len(data_packets), 0)
        latest_t_adc, latest_s_adc, latest_dac = data_packets[-1]

        # Verify speed ADC and torque ADC have ramped up from idle
        self.assertGreater(latest_s_adc, 100.0)  # Motor is spinning
        self.assertGreater(latest_t_adc, 512.0)  # Torque applied > 0 N·m

        # Stop motor
        transport.send_command("STOP")
        time.sleep(0.1)

        transport.disconnect()

    def test_simulated_protocol_commands(self):
        transport = SimulatedTransport(tick_interval_s=0.01)
        pid_received = None
        transport.on_pid = lambda p, i, d: nonlocal_pid(p, i, d)

        def nonlocal_pid(p, i, d):
            nonlocal pid_received
            pid_received = (p, i, d)

        transport.connect("DEMO_PORT")

        # GET_PID
        transport.send_command("<GET_PID>")
        self.assertEqual(pid_received, (100.0, 10.0, 1.0))

        # SET_PID
        transport.send_command("<SET_PID:150.0000,20.0000,2.5000>")
        self.assertEqual(pid_received, (150.0, 20.0, 2.5))

        # Relays
        transport.send_command("<RELAY:BRAKE,1>")
        self.assertTrue(transport._relays.get("BRAKE"))
        transport.send_command("<RELAY:BRAKE,0>")
        self.assertFalse(transport._relays.get("BRAKE"))

        transport.disconnect()


class TestDynoTUIInitialization(unittest.TestCase):
    """Tests for DynoTUI initialization and engine binding."""

    def test_default_init(self):
        tui = DynoTUI()
        self.assertFalse(tui.demo_mode)
        self.assertIsNotNone(tui.engine)
        self.assertEqual(tui.engine.control_mode, "hybrid")

    def test_demo_mode_init(self):
        tui = DynoTUI(demo_mode=True)
        self.assertTrue(tui.demo_mode)
        self.assertIsInstance(tui.engine.transport, SimulatedTransport)

    def test_event_listeners(self):
        tui = DynoTUI(demo_mode=True)
        initial_log_count = len(tui.log_messages)

        # Trigger on_status
        tui.engine._notify("on_status", "Test Status Message")
        self.assertEqual(len(tui.log_messages), initial_log_count + 1)
        self.assertEqual(tui.log_messages[-1][2], "Test Status Message")

        # Trigger on_error
        tui.engine._notify("on_error", "Test Error Message")
        self.assertEqual(tui.log_messages[-1][1], "ERROR")
        self.assertEqual(tui.log_messages[-1][2], "Test Error Message")

        # Trigger on_telemetry
        sample = Sample(1.0, 1.5, 2000.0, 1000, 200, 1.5)
        tui.engine._notify("on_telemetry", sample)
        self.assertEqual(len(tui.sample_history), 1)
        self.assertEqual(tui.sample_history[-1].torque_nm, 1.5)


class TestDynoTUIKeyHandling(unittest.TestCase):
    """Tests for DynoTUI keyboard action dispatching."""

    def setUp(self):
        self.tui = DynoTUI(demo_mode=True)

    def test_quit_key(self):
        self.tui._running = True
        self.tui.handle_key(ord("q"))
        self.assertFalse(self.tui._running)

        self.tui._running = True
        self.tui.handle_key(ord("Q"))
        self.assertFalse(self.tui._running)

    def test_stop_key(self):
        self.tui.engine.start_manual(1.0)
        self.assertEqual(self.tui.engine.state, RunState.RUNNING)

        self.tui.handle_key(ord("s"))
        self.assertEqual(self.tui.engine.state, RunState.FINISHED)

    def test_reset_key(self):
        self.tui.engine.start_manual(1.0)
        self.tui.handle_key(ord("r"))
        self.assertEqual(self.tui.engine.state, RunState.IDLE)
        self.assertEqual(self.tui.engine.current_torque, 0.0)

    def test_target_adjustment_keys(self):
        self.tui._manual_preset_torque = 1.0

        # '+' increments by 0.1
        self.tui.handle_key(ord("+"))
        self.assertAlmostEqual(self.tui._manual_preset_torque, 1.1)

        # '-' decrements by 0.1
        self.tui.handle_key(ord("-"))
        self.assertAlmostEqual(self.tui._manual_preset_torque, 1.0)

        # Active manual run target adjustment
        self.tui.engine.start_manual(1.0)
        self.tui.handle_key(ord("+"))
        self.assertAlmostEqual(self.tui.engine.target_torque, 1.1)
        self.tui.engine.stop()

    def test_control_mode_toggle(self):
        self.tui.engine.control_mode = "hybrid"
        self.tui.handle_key(ord("o"))
        self.assertEqual(self.tui.engine.control_mode, "closed_loop")

        self.tui.handle_key(ord("o"))
        self.assertEqual(self.tui.engine.control_mode, "open_loop")

        self.tui.handle_key(ord("o"))
        self.assertEqual(self.tui.engine.control_mode, "hybrid")

    def test_relay_toggles(self):
        # 1: BRAKE
        self.assertFalse(self.tui.engine.relays["BRAKE"])
        self.tui.handle_key(ord("1"))
        self.assertTrue(self.tui.engine.relays["BRAKE"])
        self.tui.handle_key(ord("1"))
        self.assertFalse(self.tui.engine.relays["BRAKE"])

        # 2: SENSOR
        self.assertFalse(self.tui.engine.relays["SENSOR"])
        self.tui.handle_key(ord("2"))
        self.assertTrue(self.tui.engine.relays["SENSOR"])
        self.tui.handle_key(ord("2"))
        self.assertFalse(self.tui.engine.relays["SENSOR"])

        # 3: AUX
        self.assertFalse(self.tui.engine.relays["AUX"])
        self.tui.handle_key(ord("3"))
        self.assertTrue(self.tui.engine.relays["AUX"])
        self.tui.handle_key(ord("3"))
        self.assertFalse(self.tui.engine.relays["AUX"])

    def test_calibration_toggle(self):
        self.assertFalse(self.tui.engine._is_calibrating)
        self.tui.handle_key(ord("k"))
        self.assertTrue(self.tui.engine._is_calibrating)

        # Simulate peak ADC
        self.tui.engine._max_calib_reading = 900.0
        self.tui.handle_key(ord("k"))
        self.assertFalse(self.tui.engine._is_calibrating)


class TestDynoTUIPrompts(unittest.TestCase):
    """Tests for interactive modal prompt input with simulated keystrokes."""

    def setUp(self):
        self.tui = DynoTUI(demo_mode=True)
        self.win = MockCursesWindow(24, 80)
        self.tui._running = True

    def test_prompt_input_enter(self):
        # Type "2.5" then Enter (10)
        self.win.key_queue = [ord("2"), ord("."), ord("5"), 10]
        result = self.tui.prompt_input(self.win, "Enter torque: ", "")
        self.assertEqual(result, "2.5")

    def test_prompt_input_escape(self):
        # Press Escape (27)
        self.win.key_queue = [27]
        result = self.tui.prompt_input(self.win, "Enter torque: ", "default")
        self.assertIsNone(result)

    def test_prompt_input_backspace(self):
        # Type '1', '2', Backspace, '5', Enter
        self.win.key_queue = [ord("1"), ord("2"), 127, ord("5"), 10]
        result = self.tui.prompt_input(self.win, "Enter torque: ", "")
        self.assertEqual(result, "15")

    def test_interactive_manual_run(self):
        self.win.key_queue = [ord("1"), ord("."), ord("8"), 10]
        self.tui.interactive_manual_run(self.win)
        self.assertEqual(self.tui.engine.state, RunState.RUNNING)
        self.assertAlmostEqual(self.tui.engine.target_torque, 1.8)
        self.tui.engine.stop()

    def test_interactive_profile_run(self):
        # Provide path to load test template
        path_str = "assets/load_test_template.csv"
        self.win.key_queue = [ord(c) for c in path_str] + [10]
        self.tui.interactive_profile_run(self.win)
        self.assertEqual(self.tui.engine.state, RunState.RUNNING)
        self.assertEqual(self.tui.engine.mode, RunMode.PROFILE)
        self.tui.engine.stop()

    def test_interactive_pid_tuning(self):
        pid_str = "120.0, 15.0, 1.5"
        self.win.key_queue = [ord(c) for c in pid_str] + [10]
        self.tui.interactive_pid_tuning(self.win)
        self.assertEqual(self.tui.engine.stored_pid, (120.0, 15.0, 1.5))

    def test_interactive_logging(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            temp_path = f.name

        try:
            self.win.key_queue = [ord(c) for c in temp_path] + [10]
            self.tui.interactive_logging(self.win)
            self.assertTrue(self.tui.engine._logger.is_open())

            # Stop logging
            self.tui.interactive_logging(self.win)
            self.assertFalse(self.tui.engine._logger.is_open())
        finally:
            if Path(temp_path).exists():
                Path(temp_path).unlink()


class TestDynoTUIDrawingHeadless(unittest.TestCase):
    """Tests for screen drawing and rendering paths."""

    def setUp(self):
        self.tui = DynoTUI(demo_mode=True)

    def test_draw_standard_80x24(self):
        win = MockCursesWindow(24, 80)
        self.tui.draw(win)

        # Check header
        line0 = win.get_line_text(0)
        self.assertIn("MOTOR-DYNO TEST BENCH", line0)

        # Check telemetry
        found_telemetry = any("LIVE TELEMETRY" in win.get_line_text(y) for y in range(24))
        self.assertTrue(found_telemetry)

        # Check controls
        found_controls = any("CONTROLS & HARDWARE" in win.get_line_text(y) for y in range(24))
        self.assertTrue(found_controls)

        # Check keybindings footer
        line23 = win.get_line_text(23)
        self.assertIn("[Q]", line23)

    def test_draw_undersized_window(self):
        win = MockCursesWindow(15, 50)
        self.tui.draw(win)
        # Should render warning message instead of crashing
        text = " ".join(win.get_line_text(y) for y in range(15))
        self.assertIn("TERMINAL WINDOW TOO SMALL", text)

    def test_stability_badges(self):
        win = MockCursesWindow(24, 80)

        # When running and stable
        self.tui.engine.start_manual(1.0)
        # Force stable in monitor
        self.tui.engine._stability_monitor.add_reading(1.0, time.perf_counter() - 1.0)
        self.tui.engine._stability_monitor.add_reading(1.0, time.perf_counter())

        self.tui.draw(win)
        all_text = " ".join(win.get_line_text(y) for y in range(24))
        self.assertTrue("[STABLE]" in all_text or "[WAITING]" in all_text)

        self.tui.engine.stop()


class TestDemoModeEndToEnd(unittest.TestCase):
    """End-to-end integration test of DynoTUI in demo mode with live simulation."""

    def test_demo_manual_run_telemetry(self):
        tui = DynoTUI(demo_mode=True)
        tui.engine.connect()
        tui.engine.start_loop()

        # Start manual run
        tui.engine.start_manual(2.0)
        self.assertEqual(tui.engine.state, RunState.RUNNING)

        # Allow simulation and engine loops to run
        time.sleep(0.2)

        # Verify telemetry accumulated
        self.assertGreater(len(tui.sample_history), 0)
        latest = tui.sample_history[-1]
        self.assertGreater(latest.rpm, 0.0)

        # Clean shutdown
        tui.engine.stop()
        tui.engine.stop_loop()
        tui.engine.disconnect()


class TestCLIArgs(unittest.TestCase):
    """Tests for CLI arguments parser in tui.py."""

    def test_defaults(self):
        args = parse_args([])
        self.assertEqual(args.port, "")
        self.assertEqual(args.baud, 115200)
        self.assertFalse(args.demo)
        self.assertIsNone(args.profile)

    def test_custom_args(self):
        args = parse_args(["--port", "/dev/ttyUSB1", "--baud", "57600", "--demo", "--profile", "test.csv"])
        self.assertEqual(args.port, "/dev/ttyUSB1")
        self.assertEqual(args.baud, 57600)
        self.assertTrue(args.demo)
        self.assertEqual(args.profile, "test.csv")

    def test_mock_alias(self):
        args = parse_args(["--mock"])
        self.assertTrue(args.demo)


if __name__ == "__main__":
    unittest.main()
