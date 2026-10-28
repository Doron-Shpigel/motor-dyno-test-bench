"""
Unit and integration tests for SerialWorker and MainWindow open-loop / SET_DAC control.
"""

import math
import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from modules.data_model import RunMode, RunState
from modules.serial_comm import SerialWorker


app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class MockSerialWorker(QObject):
    """Headless mock of SerialWorker for testing MainWindow routing."""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    ready = pyqtSignal()
    pong_received = pyqtSignal()
    ack_received = pyqtSignal(str)
    error_received = pyqtSignal(str)
    pid_received = pyqtSignal(float, float, float)
    data_received = pyqtSignal(float, float, int)
    speed_received = pyqtSignal(int)
    torque_received = pyqtSignal(float)
    dac_received = pyqtSignal(int)
    raw_line_received = pyqtSignal(str)

    def __init__(self, port: str = "COM_MOCK", parent=None):
        super().__init__(parent)
        self.port = port
        self.sent_commands: list[str] = []
        self._running = False

    def send_command(self, cmd: str) -> None:
        self.sent_commands.append(cmd)

    def send_start(self) -> None:
        self.send_command("START")

    def send_stop(self) -> None:
        self.send_command("STOP")

    def send_reset(self) -> None:
        self.send_command("RESET")

    def send_ping(self) -> None:
        self.send_command("PING")

    def send_get_pid(self) -> None:
        self.send_command("<GET_PID>")

    def send_set_pid(self, kp: float, ki: float, kd: float) -> None:
        self.send_command(f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>")

    def send_set_torque(self, torque_nm: float) -> None:
        self.send_command(f"<SET_TORQUE:{torque_nm:.2f}>")

    def send_set_dac(self, dac_val: int | float) -> None:
        clamped = max(0, min(4095, int(round(float(dac_val)))))
        self.send_command(f"<SET_DAC:{clamped}>")

    def send_relay(self, name: str, state: bool | int) -> None:
        val = 1 if state else 0
        self.send_command(f"<RELAY:{name.upper()},{val}>")


class TestSerialWorkerCommands(unittest.TestCase):
    """Test command generation and boundary checks on SerialWorker."""

    def setUp(self):
        self.worker = SerialWorker(port="TEST_PORT", boot_delay=0.0)

    def test_send_set_dac_standard(self):
        self.worker.send_set_dac(1024)
        cmd = self.worker._queue.get_nowait()
        self.assertEqual(cmd, "<SET_DAC:1024>")

    def test_send_set_dac_boundary_clamping(self):
        # Clamping negative
        self.worker.send_set_dac(-50)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

        # Clamping max overflow
        self.worker.send_set_dac(5000)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:4095>")

        # Exact limits
        self.worker.send_set_dac(0)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")
        self.worker.send_set_dac(4095)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:4095>")

    def test_send_set_dac_non_finite_and_types(self):
        # Floats rounded
        self.worker.send_set_dac(512.6)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:513>")

        # NaN and Inf safely fall back to 0
        self.worker.send_set_dac(float("nan"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")
        self.worker.send_set_dac(float("inf"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_DAC:0>")

    def test_send_set_torque(self):
        self.worker.send_set_torque(2.75)
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:2.75>")

        # Non-finite falls back to 0.00
        self.worker.send_set_torque(float("nan"))
        self.assertEqual(self.worker._queue.get_nowait(), "<SET_TORQUE:0.00>")

    def test_send_relay(self):
        self.worker.send_relay("brake", True)
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:BRAKE,1>")

        self.worker.send_relay("Sensor", False)
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:SENSOR,0>")

        self.worker.send_relay("aux", 1)
        self.assertEqual(self.worker._queue.get_nowait(), "<RELAY:AUX,1>")


class TestSerialWorkerParsing(unittest.TestCase):
    """Test line parsing in SerialWorker."""

    def setUp(self):
        self.worker = SerialWorker(port="TEST_PORT", boot_delay=0.0)

    def test_parse_ack_set_dac(self):
        acks = []
        self.worker.ack_received.connect(acks.append)
        self.worker._parse_line("ACK:SET_DAC:2048")
        self.assertEqual(acks, ["SET_DAC:2048"])

    def test_parse_ack_relay(self):
        acks = []
        self.worker.ack_received.connect(acks.append)
        self.worker._parse_line("ACK:RELAY:BRAKE,1")
        self.assertEqual(acks, ["RELAY:BRAKE,1"])

    def test_parse_dac_init_err(self):
        errors = []
        self.worker.error_received.connect(errors.append)
        self.worker._parse_line("DAC_INIT_ERR:0x04")
        self.assertEqual(errors, ["DAC_INIT_ERR:0x04"])

    def test_parse_data_frame(self):
        data_packets = []
        self.worker.data_received.connect(lambda t, s, d: data_packets.append((t, s, d)))
        self.worker._parse_line("<DATA:2.45,1200.0,980>")
        self.assertEqual(len(data_packets), 1)
        self.assertAlmostEqual(data_packets[0][0], 2.45)
        self.assertAlmostEqual(data_packets[0][1], 1200.0)
        self.assertEqual(data_packets[0][2], 980)


class TestMainWindowOpenLoopAndHybrid(unittest.TestCase):
    """Test MainWindow open-loop and hybrid control behavior with SET_DAC."""

    def setUp(self):
        self.window = MainWindow()
        self.mock_worker = MockSerialWorker(parent=self.window)
        self.window._worker = self.mock_worker
        self.window._connected = True

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def test_open_loop_manual_mode_always_sends_set_dac(self):
        """In Open-Loop mode, manual setpoint changes send SET_DAC regardless of RPM."""
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("open_loop")

        # 2.5 N·m on a 5.0 N·m dyno -> DAC ~ 2048
        self.window._calibration.max_torque_nm = 5.0
        self.window._last_rpm = 1500.0 # Motor is spinning fast!

        self.window._on_manual_torque_changed(2.5)

        self.assertIn("<SET_DAC:2048>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)

    def test_hybrid_mode_initial_torque_sends_set_dac_before_rpm(self):
        """In Hybrid mode, before RPM is registered (RPM <= 1.0), SET_DAC is sent."""
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("hybrid")
        self.window._calibration.max_torque_nm = 5.0
        self.window._last_rpm = 0.0 # Stationary motor

        self.window._on_manual_torque_changed(1.0) # 1.0 / 5.0 * 4095 = 819

        self.assertIn("<SET_DAC:819>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)

    def test_hybrid_mode_hands_over_to_pid_when_rpm_registered(self):
        """In Hybrid mode, when RPM > 1.0, _on_tick transitions from open-loop DAC to closed-loop PID."""
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("hybrid")
        self.window._current_target_torque = 2.0
        self.window._pid_active = False

        # Motor spins up
        self.window._last_rpm = 50.0
        self.window._on_tick()

        self.assertIn("<SET_TORQUE:2.00>", self.mock_worker.sent_commands)
        self.assertTrue(self.window._pid_active)

    def test_hybrid_mode_reverts_to_dac_if_motor_stalls(self):
        """In Hybrid mode, if motor stalls back to RPM <= 1.0, it reverts to SET_DAC to avoid windup."""
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("hybrid")
        self.window._current_target_torque = 2.5
        self.window._pid_active = True # Was running in PID

        # Motor stalls
        self.window._last_rpm = 0.0
        self.window._on_tick()

        self.assertIn("<SET_DAC:2048>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)

    def test_start_manual_preserves_target_torque(self):
        """Starting manual run must preserve the user-configured torque and not reset to 0."""
        self.window._ctrl._manual_torque = 3.2
        self.window._ctrl._update_manual_display()

        self.window._on_start_manual()

        self.assertEqual(self.window._current_target_torque, 3.2)
        self.assertEqual(self.window._ctrl.get_manual_torque(), 3.2)

    def test_relay_control_routing(self):
        """Toggling relay buttons in ControlPanel routes <RELAY:...> via mock worker."""
        self.window._ctrl._brake_relay_btn.setChecked(True)
        self.assertIn("<RELAY:BRAKE,1>", self.mock_worker.sent_commands)

        self.window._ctrl._sensor_relay_btn.setChecked(True)
        self.assertIn("<RELAY:SENSOR,1>", self.mock_worker.sent_commands)

        self.window._ctrl._aux_relay_btn.setChecked(True)
        self.assertIn("<RELAY:AUX,1>", self.mock_worker.sent_commands)


if __name__ == "__main__":
    unittest.main()
