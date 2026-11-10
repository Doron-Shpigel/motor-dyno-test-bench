"""
Adversarial tests for closed-loop stepping logic and profile orchestrator in MainWindow.

Tests:
  - Unexpected serial disconnection mid-profile
  - Double-start suppression while already running
  - Hybrid mode chatter around the 1.0 RPM threshold
  - Profile handling of zero-torque setpoints (min_abs_tolerance gating)
  - Mid-run dynamic stability parameter updates
  - Prevent starting uninitialized or empty profiles
  - Recovery from step timeout into subsequent normal stability advancement
"""

from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from modules.data_model import RunMode, RunState
from modules.plf import PiecewiseLinearFunction

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class MockSerialWorker(QObject):
    """Headless mock of SerialWorker for adversarial testing."""

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
        self.send_command(f"<SET_TORQUE:{float(torque_nm):.2f}>")

    def send_set_dac(self, dac_val: int | float) -> None:
        clamped = max(0, min(4095, int(round(float(dac_val)))))
        self.send_command(f"<SET_DAC:{clamped}>")

    def send_relay(self, name: str, state: bool | int) -> None:
        val = 1 if state else 0
        self.send_command(f"<RELAY:{name.upper()},{val}>")

    def stop(self) -> None:
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:
        return True


def create_mock_plf(torques: list[float], times: list[float] | None = None) -> PiecewiseLinearFunction:
    plf = PiecewiseLinearFunction()
    if times is None:
        times = [float(i * 5.0) for i in range(len(torques))]
    plf.times = np.array(times, dtype=float)
    plf.torques = np.array(torques, dtype=float)
    plf.duration = float(plf.times[-1])
    plf._loaded = True
    return plf


class TestAdversarialClosedLoopStepping(unittest.TestCase):
    """Adversarial scenarios during profile stepping."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dyno_adv_stepping_")
        self.window = MainWindow()
        self.window._logger.open_temp = lambda: self.window._logger.open_explicit(
            Path(self.temp_dir) / "temp_run.csv"
        )
        self.mock_worker = MockSerialWorker(parent=self.window)
        self.window._worker = self.mock_worker
        self.window._connected = True

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unexpected_serial_disconnect_mid_profile(self):
        """Sudden disconnect mid-profile aborts the run cleanly."""
        self.window._plf = create_mock_plf([1.0, 2.5, 4.0])
        self.window._on_start_profile()
        self.assertEqual(self.window._session.state, RunState.RUNNING)

        # Trigger disconnect event
        self.window._on_serial_disconnected()

        # Session must be stopped
        self.assertEqual(self.window._session.state, RunState.FINISHED)
        self.assertFalse(self.window._connected)
        self.assertFalse(self.window._timer.isActive())

    def test_double_start_is_safely_ignored(self):
        """Calling start when already RUNNING must not reset or corrupt state."""
        self.window._plf = create_mock_plf([1.5, 3.0, 4.5])
        self.window._on_start_profile()
        self.window._current_step_idx = 1
        self.window._current_target_torque = 3.0

        # Attempt second start while still running
        self.window._on_start_profile()

        # Must still be at step 1 with target 3.0
        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 3.0)

        # Attempt manual start while profile is running
        self.window._on_start_manual()
        self.assertEqual(self.window._session.run_mode, RunMode.PROFILE)
        self.assertEqual(self.window._current_step_idx, 1)

    def test_hybrid_mode_rpm_boundary_rapid_chatter(self):
        """Rapid chatter around 1.0 RPM threshold toggles cleanly between DAC and PID."""
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("hybrid")
        self.window._current_target_torque = 2.5
        self.mock_worker.sent_commands.clear()

        # Rapidly chatter RPM across 1.0 boundary for 10 ticks
        rpm_sequence = [0.8, 1.2, 0.9, 1.1, 0.95, 1.05, 0.5, 1.5, 0.0, 20.0]
        for rpm in rpm_sequence:
            self.window._last_rpm = rpm
            self.window._on_tick()

        # Verify command alternations occurred without exceptions
        sent = self.mock_worker.sent_commands
        self.assertTrue(any("<SET_DAC:" in cmd for cmd in sent))
        self.assertTrue(any("<SET_TORQUE:2.50>" in cmd for cmd in sent))

    def test_zero_torque_setpoint_stability_gating(self):
        """Zero-torque setpoints in profiles use min_abs_tolerance floor for stability."""
        # Profile starting with 0.0 N·m (e.g. idle baseline)
        self.window._plf = create_mock_plf([0.0, 2.0])
        self.window._stability_monitor.set_parameters(
            tolerance_pct=2.0, settling_time_s=0.5, min_abs_tolerance=0.1
        )
        self.window._on_start_profile()
        self.window._last_rpm = 100.0
        self.assertEqual(self.window._current_step_idx, 0)
        self.assertAlmostEqual(self.window._current_target_torque, 0.0)

        # Add readings near 0.0 N·m (within 0.1 N·m floor)
        now = time.perf_counter()
        for i in range(15):
            self.window._stability_monitor.add_reading(0.04, timestamp=now + i * 0.05)

        with patch("time.perf_counter", return_value=now + 0.8):
            self.window._on_tick()

        # Advances to step 1
        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 2.0)

    def test_mid_run_dynamic_stability_parameter_updates(self):
        """Updating stability parameters dynamically alters subsequent gating."""
        self.window._plf = create_mock_plf([2.0, 4.0])
        self.window._stability_monitor.set_parameters(tolerance_pct=1.0, settling_time_s=2.0)
        self.window._on_start_profile()
        self.window._last_rpm = 100.0

        # Readings at 2.05 N·m (2.5% error, unstable under 1.0% tolerance)
        now = time.perf_counter()
        for i in range(25):
            self.window._stability_monitor.add_reading(2.05, timestamp=now + i * 0.05)

        with patch("time.perf_counter", return_value=now + 1.3):
            self.window._on_tick()
        self.assertEqual(self.window._current_step_idx, 0)  # Still at 0

        # Now dynamically relax tolerance to 5.0% and settling time to 1.0s
        self.window._on_update_stability_params(5.0, 1.0)
        self.assertAlmostEqual(self.window._stability_monitor.tolerance_pct, 5.0)
        self.assertAlmostEqual(self.window._stability_monitor.settling_time_s, 1.0)

        # Next tick now evaluates to stable!
        with patch("time.perf_counter", return_value=now + 1.35):
            self.window._on_tick()
        self.assertEqual(self.window._current_step_idx, 1)

    def test_empty_or_unloaded_profile_rejected(self):
        """Attempting to start profile when none is loaded must show error and abort."""
        self.window._plf = PiecewiseLinearFunction()  # unloaded
        with patch.object(self.window, "_show_error") as mock_err:
            self.window._on_start_profile()
            mock_err.assert_called_once()
            self.assertEqual(self.window._session.state, RunState.IDLE)

    def test_recovery_from_step_timeout_to_normal_advancement(self):
        """A timed-out step advances, and the next step can still settle normally."""
        self.window._plf = create_mock_plf([1.0, 2.0, 3.0])
        self.window._step_timeout_s = 2.0
        self.window._stability_monitor.set_parameters(settling_time_s=0.5, tolerance_pct=2.0)
        self.window._on_start_profile()
        self.window._last_rpm = 100.0

        # Step 0 never stabilizes -> triggers timeout
        now = time.perf_counter()
        self.window._step_start_time = now - 3.0
        with patch("time.perf_counter", return_value=now):
            self.window._on_tick()

        # Successfully advanced to step 1 via timeout fallback
        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 2.0)

        # Step 1 achieves authentic stability!
        now2 = now + 1.0
        for i in range(15):
            self.window._stability_monitor.add_reading(2.0, timestamp=now2 + i * 0.05)

        with patch("time.perf_counter", return_value=now2 + 0.8):
            self.window._on_tick()

        # Advanced to step 2 via authentic stability
        self.assertEqual(self.window._current_step_idx, 2)
        self.assertAlmostEqual(self.window._current_target_torque, 3.0)


if __name__ == "__main__":
    unittest.main()
