"""
End-to-End Integration tests for motor-dyno-test-bench.

Tests:
  - Full E2E profile execution workflow with real CSV profile (assets/load_test_template.csv)
  - Stepping progression through all setpoints to RunState.FINISHED
  - Data logging via CSVLogger with schema verification
  - Run statistics updates in UI
  - Manual run workflow with setpoint changes and stability badge synchronization
  - Hardware relay orchestration and automatic safety shutoff on run stop
"""

import csv
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from modules.data_model import RunMode, RunState

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class MockSerialWorker(QObject):
    """Headless mock of SerialWorker for integration testing."""

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


class TestE2EIntegration(unittest.TestCase):
    """End-to-end integration test suite."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dyno_e2e_")
        self.window = MainWindow()
        self.window._logger.open_temp = lambda: self.window._logger.open_explicit(
            Path(self.temp_dir) / "temp_run.csv"
        )
        self.mock_worker = MockSerialWorker(parent=self.window)
        self.window._worker = self.mock_worker
        self.window._connected = True
        self.window._calibration.output_dir = Path(self.temp_dir)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_e2e_profile_execution_workflow(self):
        """Full end-to-end profile execution with CSV profile, telemetry streaming, and logging."""
        profile_path = Path("assets/load_test_template.csv")
        self.assertTrue(profile_path.exists(), "load_test_template.csv should exist in assets")

        # Load profile
        self.window._plf.load_csv(profile_path)
        self.window._ctrl.set_profile_info(self.window._plf)
        total_steps = len(self.window._plf.torques)
        self.assertGreater(total_steps, 0)

        # Fast settling for automated test: 0.1s settling time, 2.0% tolerance
        self.window._stability_monitor.set_parameters(
            tolerance_pct=2.0,
            settling_time_s=0.1,
            min_abs_tolerance=0.1,
        )
        self.window._stability_monitor.max_staleness_s = 0.5

        # Start Profile Run
        self.window._on_start_profile()
        self.assertEqual(self.window._session.state, RunState.RUNNING)
        self.assertEqual(self.window._session.run_mode, RunMode.PROFILE)
        self.assertIn("START", self.mock_worker.sent_commands)

        # Motor spins up
        speed_val = 1000.0  # speed * 0.5 = 500 RPM > 1.0

        # Progress through each setpoint step-by-step
        curr_sim_time = time.perf_counter()
        for step_idx in range(total_steps):
            expected_target = float(self.window._plf.torques[step_idx])
            self.assertEqual(self.window._current_step_idx, step_idx)
            self.assertAlmostEqual(self.window._current_target_torque, expected_target, places=2)

            # Ingest stable telemetry around target torque for > settling_time (0.15s)
            target_adc = 512.0 + (expected_target / self.window._calibration.torque_per_count)
            for i in range(5):
                curr_sim_time += 0.03
                # Stream via Qt slot
                with patch("time.perf_counter", return_value=curr_sim_time):
                    self.window._on_data_received(target_adc, speed_val, 1500)

            # Check stability status badge is now True
            self.assertTrue(self.window._stability_monitor.is_stable(expected_target, curr_sim_time))

            # Trigger control-loop tick
            curr_sim_time += 0.01
            with patch("time.perf_counter", return_value=curr_sim_time):
                self.window._on_tick()

        # After the last step, profile run should have transitioned to FINISHED
        self.assertEqual(self.window._session.state, RunState.FINISHED)
        self.assertIn("STOP", self.mock_worker.sent_commands)
        self.assertGreater(self.window._session.sample_count(), 0)

        # Save log file
        self.window._on_save_log()
        self.assertTrue(self.window._log_saved)

        # Verify saved CSV log in output directory
        log_files = list(Path(self.temp_dir).glob("dyno_log_*.csv"))
        self.assertEqual(len(log_files), 1)
        saved_csv = log_files[0]

        with saved_csv.open("r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertEqual(header, ["elapsed_s", "torque_nm", "rpm", "dac_raw", "adc_raw"])
            rows = list(reader)
            self.assertGreater(len(rows), 0)

        # Verify run stats label in UI was updated
        samples_text = self.window._ctrl._samples_val.text()
        self.assertEqual(samples_text, str(self.window._session.sample_count()))

    def test_e2e_manual_run_and_stability_badge(self):
        """E2E manual run with dynamic setpoint changes and stability badge verification."""
        self.window._stability_monitor.set_parameters(settling_time_s=0.1, tolerance_pct=2.0)
        self.window._stability_monitor.max_staleness_s = 0.5
        self.window._ctrl._manual_torque = 2.0
        self.window._ctrl._update_manual_display()

        # Start manual run
        self.window._on_start_manual()
        self.assertEqual(self.window._session.state, RunState.RUNNING)
        self.assertEqual(self.window._session.run_mode, RunMode.MANUAL)
        self.assertAlmostEqual(self.window._current_target_torque, 2.0)

        # Stream unstable telemetry first
        now = time.perf_counter()
        with patch("time.perf_counter", return_value=now):
            self.window._on_data_received(512.0, 500.0, 1000)  # 0 N·m when target is 2.0
            self.window._on_tick()

        self.assertEqual(self.window._settings_tab._status_label.text(), "WAITING")

        # Stream stable telemetry at 2.0 N·m
        adc_2nm = 512.0 + (2.0 / self.window._calibration.torque_per_count)
        for i in range(5):
            now += 0.03
            with patch("time.perf_counter", return_value=now):
                self.window._on_data_received(adc_2nm, 500.0, 1000)

        with patch("time.perf_counter", return_value=now + 0.01):
            self.window._on_tick()

        self.assertEqual(self.window._settings_tab._status_label.text(), "STABLE")

        # Change setpoint to 3.5 N·m
        self.window._on_manual_torque_changed(3.5)
        self.assertEqual(self.window._settings_tab._status_label.text(), "WAITING")
        self.assertAlmostEqual(self.window._current_target_torque, 3.5)

        # Stop manual run
        self.window._on_stop()
        self.assertEqual(self.window._session.state, RunState.FINISHED)

    def test_e2e_hardware_relays_safety_shutoff(self):
        """Toggling relays routes commands and stopping a run safely disengages all relays."""
        self.window._ctrl._brake_relay_btn.setChecked(True)
        self.assertIn("<RELAY:BRAKE,1>", self.mock_worker.sent_commands)

        self.window._ctrl._sensor_relay_btn.setChecked(True)
        self.assertIn("<RELAY:SENSOR,1>", self.mock_worker.sent_commands)

        self.window._ctrl._aux_relay_btn.setChecked(True)
        self.assertIn("<RELAY:AUX,1>", self.mock_worker.sent_commands)

        # Start and then stop a run
        self.window._session.state = RunState.RUNNING
        self.window._on_stop()

        # All relay buttons must be disengaged
        self.assertFalse(self.window._ctrl._brake_relay_btn.isChecked())
        self.assertFalse(self.window._ctrl._sensor_relay_btn.isChecked())
        self.assertFalse(self.window._ctrl._aux_relay_btn.isChecked())


if __name__ == "__main__":
    unittest.main()
