"""
Unit and integration tests for closed-loop profile stepping and mode transitions in MainWindow.

Tests:
  - Profile execution stepping logic with PiecewiseLinearFunction
  - Stability gating: setpoints do not advance until stability monitor confirms settled state
  - Safety step timeout fallback: setpoint advances if stability is not achieved within timeout
  - Profile completion on the final step
  - Control mode transitions (Open-Loop, Hybrid, Closed-Loop)
  - UI stability badge synchronization
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

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
    """Headless mock of SerialWorker for MainWindow routing tests."""

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
    """Helper to construct an in-memory loaded PLF."""
    plf = PiecewiseLinearFunction()
    if times is None:
        times = [float(i * 5.0) for i in range(len(torques))]
    plf.times = np.array(times, dtype=float)
    plf.torques = np.array(torques, dtype=float)
    plf.duration = float(plf.times[-1])
    plf._loaded = True
    return plf


class TestClosedLoopStepping(unittest.TestCase):
    """Test stability gating and stepping logic in MainWindow."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dyno_stepping_")
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

    def test_start_profile_initializes_step_0(self):
        """Starting profile initializes step 0 and commands initial torque setpoint."""
        self.window._plf = create_mock_plf([1.5, 3.0, 4.5])
        self.window._on_start_profile()

        self.assertEqual(self.window._session.state, RunState.RUNNING)
        self.assertEqual(self.window._session.run_mode, RunMode.PROFILE)
        self.assertEqual(self.window._current_step_idx, 0)
        self.assertAlmostEqual(self.window._current_target_torque, 1.5)
        self.assertIn("START", self.mock_worker.sent_commands)
        # In hybrid mode with initial stationary motor (_last_rpm == 0.0), SET_DAC is commanded
        self.assertIn("<SET_DAC:1228>", self.mock_worker.sent_commands)

    def test_profile_does_not_advance_when_unstable(self):
        """Setpoints do not advance while stability monitor reports unstable."""
        self.window._plf = create_mock_plf([1.5, 3.0, 4.5])
        self.window._on_start_profile()
        self.mock_worker.sent_commands.clear()

        # Telemetry is fluctuating outside tolerance
        now = time.perf_counter()
        for i in range(10):
            self.window._stability_monitor.add_reading(2.5, timestamp=now + i * 0.05)

        self.window._on_tick()

        # Should remain at step 0
        self.assertEqual(self.window._current_step_idx, 0)
        self.assertAlmostEqual(self.window._current_target_torque, 1.5)
        self.assertEqual(len(self.mock_worker.sent_commands), 0)

    def test_profile_advances_when_stable(self):
        """When stable steady-state is reached, profile advances to next setpoint."""
        self.window._plf = create_mock_plf([1.5, 3.0, 4.5])
        self.window._stability_monitor.set_parameters(tolerance_pct=2.0, settling_time_s=1.0)
        self.window._on_start_profile()
        # Motor spins up
        self.window._last_rpm = 500.0
        self.mock_worker.sent_commands.clear()

        # Feed stable readings at 1.5 N·m for 1.2s (> settling_time 1.0s)
        now = time.perf_counter()
        for i in range(25):
            self.window._stability_monitor.add_reading(1.5, timestamp=now + i * 0.05)

        with patch("time.perf_counter", return_value=now + 1.25):
            self.window._on_tick()

        # Should advance to step 1
        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 3.0)
        # Since _last_rpm > 1.0, PID SET_TORQUE is commanded
        self.assertIn("<SET_TORQUE:3.00>", self.mock_worker.sent_commands)
        # Buffer was reset
        self.assertEqual(self.window._stability_monitor.reading_count(), 0)

    def test_full_profile_execution_to_completion(self):
        """Verify step-by-step advancement through all steps to completion."""
        torques = [1.0, 2.5]
        self.window._plf = create_mock_plf(torques)
        self.window._stability_monitor.set_parameters(tolerance_pct=2.0, settling_time_s=0.5)
        self.window._on_start_profile()
        self.window._last_rpm = 500.0

        # Step 0: Feed stable readings around 1.0 N·m
        now = time.perf_counter()
        for i in range(15):
            self.window._stability_monitor.add_reading(1.0, timestamp=now + i * 0.05)

        with patch("time.perf_counter", return_value=now + 0.75):
            self.window._on_tick()

        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 2.5)

        # Step 1: Feed stable readings around 2.5 N·m
        now2 = now + 1.0
        for i in range(15):
            self.window._stability_monitor.add_reading(2.5, timestamp=now2 + i * 0.05)

        with patch("time.perf_counter", return_value=now2 + 0.75):
            self.window._on_tick()

        # Profile completed
        self.assertEqual(self.window._session.state, RunState.FINISHED)
        self.assertIn("STOP", self.mock_worker.sent_commands)

    def test_safety_step_timeout_advances_setpoint(self):
        """If step never achieves stability, timeout advances to next setpoint."""
        self.window._plf = create_mock_plf([1.0, 2.5, 4.0])
        self.window._step_timeout_s = 5.0
        self.window._on_start_profile()
        self.window._last_rpm = 500.0
        self.mock_worker.sent_commands.clear()

        # System is unstable
        now = time.perf_counter()
        self.window._stability_monitor.add_reading(0.5, timestamp=now)

        # Simulate timeout (step_start_time was 6 seconds ago)
        self.window._step_start_time = now - 6.0
        with patch("time.perf_counter", return_value=now):
            self.window._on_tick()

        # Advanced to step 1 despite not being stable
        self.assertEqual(self.window._current_step_idx, 1)
        self.assertAlmostEqual(self.window._current_target_torque, 2.5)
        self.assertIn("<SET_TORQUE:2.50>", self.mock_worker.sent_commands)

    def test_safety_step_timeout_on_last_step_finishes(self):
        """If last step times out, profile finishes gracefully."""
        self.window._plf = create_mock_plf([1.0, 2.5])
        self.window._step_timeout_s = 5.0
        self.window._on_start_profile()

        # Set to last step
        self.window._current_step_idx = 1
        self.window._current_target_torque = 2.5
        now = time.perf_counter()
        self.window._step_start_time = now - 6.0

        with patch("time.perf_counter", return_value=now):
            self.window._on_tick()

        self.assertEqual(self.window._session.state, RunState.FINISHED)
        self.assertIn("STOP", self.mock_worker.sent_commands)


class TestControlModeTransitions(unittest.TestCase):
    """Test transitions between Open-Loop, Hybrid, and Closed-Loop modes."""

    def setUp(self):
        self.window = MainWindow()
        self.mock_worker = MockSerialWorker(parent=self.window)
        self.window._worker = self.mock_worker
        self.window._connected = True
        self.window._calibration.max_torque_nm = 5.0

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def test_open_loop_mode_always_sends_set_dac(self):
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("open_loop")

        self.window._last_rpm = 2000.0  # High RPM
        self.window._command_torque_setpoint(2.5)  # 2.5/5.0 * 4095 ~ 2048

        self.assertIn("<SET_DAC:2048>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)

    def test_closed_loop_mode_always_sends_set_torque(self):
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("closed_loop")

        self.window._last_rpm = 0.0  # Zero RPM
        self.window._command_torque_setpoint(3.5)

        self.assertIn("<SET_TORQUE:3.50>", self.mock_worker.sent_commands)
        self.assertTrue(self.window._pid_active)

    def test_hybrid_mode_rpm_transition_dynamics(self):
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._ctrl.set_manual_control_mode("hybrid")
        self.window._current_target_torque = 2.0

        # Phase 1: Stationary -> commands DAC
        self.window._last_rpm = 0.0
        self.window._command_torque_setpoint(2.0)
        self.assertIn("<SET_DAC:1638>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)
        self.mock_worker.sent_commands.clear()

        # Phase 2: Spins up -> _on_tick transitions to PID
        self.window._last_rpm = 50.0
        self.window._on_tick()
        self.assertIn("<SET_TORQUE:2.00>", self.mock_worker.sent_commands)
        self.assertTrue(self.window._pid_active)
        self.mock_worker.sent_commands.clear()

        # Phase 3: Stalls -> _on_tick reverts to DAC
        self.window._last_rpm = 0.0
        self.window._on_tick()
        self.assertIn("<SET_DAC:1638>", self.mock_worker.sent_commands)
        self.assertFalse(self.window._pid_active)

    def test_manual_mode_changed_slot_updates_command(self):
        self.window._session.state = RunState.RUNNING
        self.window._session.run_mode = RunMode.MANUAL
        self.window._current_target_torque = 2.5
        self.window._last_rpm = 100.0

        # Switch to open-loop
        self.window._ctrl.set_manual_control_mode("open_loop")
        self.window._on_manual_mode_changed("open_loop")
        self.assertIn("<SET_DAC:2048>", self.mock_worker.sent_commands)


if __name__ == "__main__":
    unittest.main()
