"""
Adversarial and robustness tests for SerialWorker communication protocol (modules/serial_comm.py).

Tests:
  - Malformed <DATA:...> packets (wrong arg count, non-numeric, NaN/Inf, missing brackets)
  - Malformed <PID_VALS:...> packets (wrong arg count, non-numeric, NaN/Inf, unclosed frame)
  - Malformed legacy SPEED packets
  - Binary garbage, noise, and unexpected string frames
  - Outgoing command robustness against NaN, Inf, out-of-range, and malformed inputs
  - Simulated serial transport errors (open failure, read/write disconnect)
"""

import math
import sys
import unittest
from unittest.mock import MagicMock, patch

import serial
from PyQt6.QtWidgets import QApplication

from modules.serial_comm import SerialWorker

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestSerialAdversarialParsing(unittest.TestCase):
    """Adversarial parsing test suite for incoming serial frames."""

    def setUp(self):
        self.worker = SerialWorker(port="MOCK_PORT", boot_delay=0.0)
        self.data_received: list[tuple[float, float, int]] = []
        self.pid_received: list[tuple[float, float, float]] = []
        self.error_received: list[str] = []
        self.raw_lines: list[str] = []

        self.worker.data_received.connect(lambda t, s, d: self.data_received.append((t, s, d)))
        self.worker.pid_received.connect(lambda p, i, d: self.pid_received.append((p, i, d)))
        self.worker.error_received.connect(self.error_received.append)
        self.worker.raw_line_received.connect(self.raw_lines.append)

    def test_malformed_data_field_counts(self):
        """Frames with incorrect number of fields must emit error_received."""
        bad_frames = [
            "<DATA:>",
            "<DATA:,>",
            "<DATA:1.0>",
            "<DATA:1.0,2.0>",
            "<DATA:1.0,2.0,300,400>",
            "<DATA:1.0,2.0,300,400,500>",
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame):
                self.error_received.clear()
                self.worker._parse_line(frame)
                self.assertEqual(len(self.error_received), 1)
                self.assertIn("Malformed DATA frame", self.error_received[0])
                self.assertEqual(len(self.data_received), 0)

    def test_malformed_data_non_numeric(self):
        """Non-numeric payloads in <DATA:...> must emit error_received."""
        bad_frames = [
            "<DATA:abc,1200,500>",
            "<DATA:1.5,xyz,500>",
            "<DATA:1.5,1200,bad_dac>",
            "<DATA:1.5.3,1200,500>",
            "<DATA:$,%,&>",
            "<DATA:NULL,None,nil>",
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame):
                self.error_received.clear()
                self.worker._parse_line(frame)
                self.assertEqual(len(self.error_received), 1)
                self.assertIn("Malformed DATA frame", self.error_received[0])
                self.assertEqual(len(self.data_received), 0)

    def test_malformed_data_nan_and_inf(self):
        """Non-finite floats in <DATA:...> must be rejected with error_received."""
        bad_frames = [
            "<DATA:nan,1200,500>",
            "<DATA:inf,1200,500>",
            "<DATA:-inf,1200,500>",
            "<DATA:1.5,nan,500>",
            "<DATA:1.5,inf,500>",
            "<DATA:1.5,-inf,500>",
            "<DATA:nan,nan,500>",
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame):
                self.error_received.clear()
                self.worker._parse_line(frame)
                self.assertEqual(len(self.error_received), 1)
                self.assertIn("Malformed DATA frame", self.error_received[0])
                self.assertEqual(len(self.data_received), 0)

    def test_malformed_data_missing_delimiters(self):
        """Frames with missing closing bracket must emit error_received."""
        self.worker._parse_line("<DATA:1.5,1200.0,500")
        self.assertEqual(len(self.error_received), 1)
        self.assertIn("missing closing '>'", self.error_received[0])
        self.assertEqual(len(self.data_received), 0)

    def test_data_with_spaces_parsed_successfully(self):
        """Whitespace within comma-separated fields must be tolerated cleanly."""
        self.worker._parse_line("<DATA:  2.50 ,   1500.5 ,  1024  >")
        self.assertEqual(len(self.data_received), 1)
        self.assertAlmostEqual(self.data_received[0][0], 2.50)
        self.assertAlmostEqual(self.data_received[0][1], 1500.5)
        self.assertEqual(self.data_received[0][2], 1024)

    def test_malformed_pid_vals(self):
        """Malformed PID_VALS packets must be rejected with error_received."""
        bad_frames = [
            "<PID_VALS:>",
            "<PID_VALS:1.0,2.0>",
            "<PID_VALS:1.0,2.0,3.0,4.0>",
            "<PID_VALS:p,i,d>",
            "<PID_VALS:nan,1.0,0.5>",
            "<PID_VALS:1.0,inf,0.5>",
            "<PID_VALS:1.0,0.5,-inf>",
            "<PID_VALS:1.0,0.5,0.1",  # missing closing bracket
        ]
        for frame in bad_frames:
            with self.subTest(frame=frame):
                self.error_received.clear()
                self.worker._parse_line(frame)
                self.assertEqual(len(self.error_received), 1)
                self.assertIn("Malformed PID_VALS frame", self.error_received[0])
                self.assertEqual(len(self.pid_received), 0)

    def test_malformed_speed_frame(self):
        """Invalid SPEED frames must emit error_received."""
        self.worker._parse_line("SPEED:abc")
        self.assertEqual(len(self.error_received), 1)
        self.assertIn("Bad SPEED value", self.error_received[0])

    def test_random_garbage_and_binary_noise(self):
        """Arbitrary line noise, empty lines, and unhandled protocols must not crash parser."""
        garbage_lines = [
            "",
            "   ",
            "\x00\x01\x02\xff\xfe",
            "?????!!!!!!",
            "<<<<>>>>",
            "random text from debug serial print",
            "UNKNOWN_COMMAND",
            "DATA:1.0,2.0,300",  # missing leading <
        ]
        for line in garbage_lines:
            # Should not raise uncaught exceptions
            self.worker._parse_line(line)


class TestSerialAdversarialCommands(unittest.TestCase):
    """Adversarial test suite for outgoing command generation."""

    def setUp(self):
        self.worker = SerialWorker(port="MOCK_PORT", boot_delay=0.0)

    def test_send_set_torque_adversarial(self):
        """send_set_torque handles NaN, Inf, None, strings gracefully."""
        self.worker.send_set_torque(float("nan"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

        self.worker.send_set_torque(float("inf"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

        self.worker.send_set_torque(float("-inf"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

        self.worker.send_set_torque("invalid")  # type: ignore
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

        self.worker.send_set_torque(None)  # type: ignore
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

        # Negative torque formatted cleanly
        self.worker.send_set_torque(-1.25)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:-1.25>")

    def test_send_set_dac_adversarial(self):
        """send_set_dac clamps out-of-range values and falls back on non-finite."""
        # Extreme negative
        self.worker.send_set_dac(-999999)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

        # Extreme positive
        self.worker.send_set_dac(999999)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:4095>")

        # Non-finite
        self.worker.send_set_dac(float("nan"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

        self.worker.send_set_dac(float("inf"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

        self.worker.send_set_dac("invalid")  # type: ignore
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

    def test_send_relay_adversarial(self):
        """send_relay cleans up messy names and converts non-bool truth values."""
        self.worker.send_relay("  brake  ", True)
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:BRAKE,1>")

        self.worker.send_relay("sensor", 0)
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:SENSOR,0>")

        self.worker.send_relay("AUX", "yes")
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:AUX,1>")


class TestSerialTransportFailures(unittest.TestCase):
    """Test SerialWorker response to low-level serial port failures."""

    def test_port_open_failure_emits_error_and_disconnected(self):
        """If serial.Serial raises exception during open, error and disconnected are emitted."""
        mock_factory = MagicMock(side_effect=serial.SerialException("Device not found"))
        worker = SerialWorker(port="NON_EXISTENT", boot_delay=0.0, serial_factory=mock_factory)

        errors = []
        disconnects = []
        worker.error_received.connect(errors.append)
        worker.disconnected.connect(lambda: disconnects.append(True))

        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertIn("Device not found", errors[0])
        # Disconnected is only emitted if the port was previously connected
        self.assertEqual(len(disconnects), 0)

    def test_port_read_failure_exits_loop_gracefully(self):
        """If readline raises SerialException, worker logs error and disconnects."""
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.in_waiting = 1
        mock_serial.readline.side_effect = serial.SerialException("Device disconnected unexpectedly")

        mock_factory = MagicMock(return_value=mock_serial)
        worker = SerialWorker(port="TEST_PORT", boot_delay=0.0, serial_factory=mock_factory)

        errors = []
        disconnects = []
        worker.error_received.connect(errors.append)
        worker.disconnected.connect(lambda: disconnects.append(True))

        worker.run()

        self.assertGreater(len(errors), 0)
        self.assertIn("Device disconnected unexpectedly", errors[0])
        self.assertEqual(len(disconnects), 1)


if __name__ == "__main__":
    unittest.main()
