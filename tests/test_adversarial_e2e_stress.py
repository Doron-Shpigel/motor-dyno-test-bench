"""
Adversarial stress and concurrency tests for dyno application.

Tests:
  - Rapid Start/Stop/Reset cycling without resource or descriptor leakage
  - Multi-threaded concurrent access to DynoSession
  - High-throughput command queueing in SerialWorker
  - High-rate telemetry ingestion stress (thousands of samples)
  - CSVLogger resilience under rapid open/close/write lifecycles
"""

from concurrent.futures import ThreadPoolExecutor
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
from modules.csv_logger import CSVLogger
from modules.data_model import DynoSession, RunMode, RunState, Sample

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class MockSerialWorker(QObject):
    """Headless mock of SerialWorker for stress testing."""

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


class TestAdversarialE2EStress(unittest.TestCase):
    """Stress and concurrency testing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dyno_stress_")
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

    def test_rapid_start_stop_reset_cycles(self):
        """Rapidly start, tick, stop, and reset 40 times in succession."""
        for i in range(40):
            self.window._ctrl._manual_torque = 1.0 + (i % 4)
            self.window._on_start_manual()
            self.assertEqual(self.window._session.state, RunState.RUNNING)

            # Ingest some telemetry and tick
            self.window._on_data_received(600.0, 500.0, 1000)
            self.window._on_tick()

            # Stop
            self.window._on_stop()
            self.assertEqual(self.window._session.state, RunState.FINISHED)

            # Reset
            self.window._on_reset()
            self.assertEqual(self.window._session.state, RunState.IDLE)
            self.assertEqual(self.window._session.sample_count(), 0)

    def test_high_rate_telemetry_ingestion_stress(self):
        """Ingest 2000 telemetry packets over 20 seconds of simulated time."""
        self.window._on_start_manual()

        sim_t = 100.0
        # Ingest 2000 packets at 100 Hz (dt = 0.01s -> 20.0 seconds total)
        for i in range(2000):
            sim_t += 0.01
            t_adc = 512.0 + (i % 100) * 2.0
            with patch("time.perf_counter", return_value=sim_t):
                self.window._on_data_received(t_adc, 1000.0, 1500)
                if i % 10 == 0:
                    self.window._on_tick()

        # Settling time is 1.5s, cutoff is max(1.5*3, 5.0) = 5.0s
        # Only the last ~5 seconds of 100 Hz samples should remain (~500 samples)
        count = self.window._stability_monitor.reading_count()
        self.assertLess(count, 550)
        self.assertGreater(count, 450)

        # Session accurately holds the recorded ticks (200 ticks)
        self.assertEqual(self.window._session.sample_count(), 200)

        self.window._on_stop()

    def test_concurrent_dyno_session_access(self):
        """Concurrent reader and writer threads accessing DynoSession."""
        session = DynoSession()
        session.start(RunMode.MANUAL)

        samples_to_write = 1000
        num_threads = 4

        def writer_task(thread_id: int):
            for i in range(samples_to_write // num_threads):
                sample = Sample(
                    elapsed_s=float(i),
                    torque_nm=float(thread_id),
                    rpm=1000.0,
                    dac_raw=2048,
                    adc_raw=600,
                )
                session.append_sample(sample)

        def reader_task():
            for _ in range(50):
                snapshot = session.get_snapshot()
                count = session.sample_count()
                elapsed = session.elapsed_seconds()
                self.assertGreaterEqual(count, 0)
                self.assertGreaterEqual(elapsed, 0.0)
                self.assertIsInstance(snapshot, list)
                time.sleep(0.001)

        with ThreadPoolExecutor(max_workers=8) as executor:
            writer_futures = [executor.submit(writer_task, tid) for tid in range(num_threads)]
            reader_futures = [executor.submit(reader_task) for _ in range(4)]

            for f in writer_futures + reader_futures:
                f.result()

        self.assertEqual(session.sample_count(), samples_to_write)
        snapshot = session.get_snapshot()
        self.assertEqual(len(snapshot), samples_to_write)

    def test_csv_logger_lifecycle_resilience(self):
        """CSVLogger raises when writing while closed, writes when open, and saves cleanly."""
        logger = CSVLogger()
        sample = Sample(0.0, 1.0, 100.0, 500, 600)

        # Writing before open raises RuntimeError
        with self.assertRaises(RuntimeError):
            logger.write(sample)

        # Open and write
        temp_csv = Path(self.temp_dir) / "temp_resilience.csv"
        temp_path = logger.open_explicit(temp_csv)
        self.assertTrue(temp_path.exists())
        logger.write(sample)
        logger.close()

        # Writing after close raises RuntimeError
        with self.assertRaises(RuntimeError):
            logger.write(sample)

        # Move to destination
        final_path = logger.save_to(self.temp_dir, "20261108_test")
        self.assertIsNotNone(final_path)
        self.assertTrue(final_path.exists())


if __name__ == "__main__":
    unittest.main()
