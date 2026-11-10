"""
Adversarial boundary and extreme condition tests across dyno modules.

Tests:
  - PiecewiseLinearFunction boundary profiles (2-point minimal, non-monotonic times, malformed headers)
  - PLF linear interpolation clamping before start and after end
  - MainWindow calibration boundary handling (peak ADC <= 512, peak ADC = 513, zero max_torque_nm)
  - Open-loop DAC calculation boundary clamping ([0, 4095])
  - StabilityMonitor zero-floor tolerance (min_abs_tolerance = 0.0)
  - Microsecond settling times and high-tolerance limits
"""

from pathlib import Path
import sys
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from modules.plf import PiecewiseLinearFunction, PLFError
from modules.stability_monitor import StabilityMonitor

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestPLFBoundaries(unittest.TestCase):
    """Test boundary conditions for PiecewiseLinearFunction."""

    def setUp(self):
        self.plf = PiecewiseLinearFunction()

    def test_query_before_loading_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.plf.torque_at(1.0)

    def test_minimal_two_point_profile(self):
        """Minimal valid PLF requires exactly 2 data points."""
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("time_s,torque_nm\n0.0,1.0\n10.0,5.0\n")
            f_path = Path(f.name)

        try:
            self.plf.load_csv(f_path)
            self.assertTrue(self.plf.is_loaded())
            self.assertAlmostEqual(self.plf.duration, 10.0)
            # Boundary points
            self.assertAlmostEqual(self.plf.torque_at(0.0), 1.0)
            self.assertAlmostEqual(self.plf.torque_at(5.0), 3.0)
            self.assertAlmostEqual(self.plf.torque_at(10.0), 5.0)
            # Clamping beyond bounds
            self.assertAlmostEqual(self.plf.torque_at(-5.0), 1.0)
            self.assertAlmostEqual(self.plf.torque_at(15.0), 5.0)
        finally:
            f_path.unlink(missing_ok=True)

    def test_single_point_profile_raises_plf_error(self):
        """Single point profile must be rejected."""
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("time_s,torque_nm\n0.0,1.0\n")
            f_path = Path(f.name)

        try:
            with self.assertRaises(PLFError):
                self.plf.load_csv(f_path)
        finally:
            f_path.unlink(missing_ok=True)

    def test_non_monotonic_times_raise_plf_error(self):
        """Decreasing or duplicate times must be rejected."""
        # Duplicate times
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f1:
            f1.write("time_s,torque_nm\n0.0,1.0\n0.0,2.0\n5.0,3.0\n")
            p1 = Path(f1.name)
        try:
            with self.assertRaises(PLFError):
                self.plf.load_csv(p1)
        finally:
            p1.unlink(missing_ok=True)

        # Decreasing times
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f2:
            f2.write("time_s,torque_nm\n0.0,1.0\n10.0,2.0\n5.0,3.0\n")
            p2 = Path(f2.name)
        try:
            with self.assertRaises(PLFError):
                self.plf.load_csv(p2)
        finally:
            p2.unlink(missing_ok=True)

    def test_missing_or_corrupt_headers(self):
        """Missing required columns must raise PLFError."""
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("time_s,speed_rpm\n0.0,1000\n10.0,2000\n")
            p = Path(f.name)
        try:
            with self.assertRaises(PLFError):
                self.plf.load_csv(p)
        finally:
            p.unlink(missing_ok=True)


class TestMainWindowBoundaries(unittest.TestCase):
    """Test calibration boundaries and DAC clamping in MainWindow."""

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        app.processEvents()

    def test_calculate_open_loop_dac_boundaries(self):
        self.window._calibration.max_torque_nm = 5.0
        # 0 N·m -> 0
        self.assertEqual(self.window._calculate_open_loop_dac(0.0), 0)
        # 5 N·m -> 4095
        self.assertEqual(self.window._calculate_open_loop_dac(5.0), 4095)
        # Negative -> clamped to 0
        self.assertEqual(self.window._calculate_open_loop_dac(-5.0), 0)
        # Overflow -> clamped to 4095
        self.assertEqual(self.window._calculate_open_loop_dac(10.0), 4095)

    def test_calculate_open_loop_dac_zero_max_torque_fallback(self):
        # Fallback prevents ZeroDivisionError
        self.window._calibration.max_torque_nm = 0.0
        dac = self.window._calculate_open_loop_dac(2.5)  # uses 5.0 default
        self.assertEqual(dac, 2048)

    def test_finish_calibration_insufficient_force(self):
        """When peak reading <= 512, calibration must fail and notify user."""
        orig_factor = self.window._calibration.torque_per_count
        self.window._max_calib_reading = 500.0  # Below 512 offset

        self.window._on_finish_calibration()

        self.assertEqual(self.window._calibration.torque_per_count, orig_factor)
        self.assertIn("Calibration failed", self.window._status_msg.text())

    def test_finish_calibration_barely_above_threshold(self):
        """Peak reading at 513 maps 1 count difference to 5 N·m."""
        self.window._max_calib_reading = 513.0
        self.window._on_finish_calibration()

        self.assertAlmostEqual(self.window._calibration.torque_per_count, 5.0 / 1.0)
        self.assertIn("Calibration successful", self.window._status_msg.text())


class TestStabilityMonitorBoundaries(unittest.TestCase):
    """Test boundary parameters for StabilityMonitor."""

    def test_zero_min_abs_tolerance_exact_matching(self):
        """When min_abs_tolerance=0.0 and target=0.0, band is 0.0 (exact match)."""
        monitor = StabilityMonitor(
            tolerance_pct=2.0,
            settling_time_s=1.0,
            min_abs_tolerance=0.0,
            max_staleness_s=0.5,
        )
        now = 1.0
        for i in range(25):
            monitor.add_reading(0.0, timestamp=now + i * 0.05)
        self.assertTrue(monitor.is_stable(0.0, current_time=now + 1.2))

        # Any deviation > 1e-9 margin fails
        monitor.add_reading(0.001, timestamp=now + 1.25)
        self.assertFalse(monitor.is_stable(0.0, current_time=now + 1.25))

    def test_extremely_short_settling_time(self):
        """Settling time of 1 ms allows rapid settling."""
        monitor = StabilityMonitor(
            tolerance_pct=2.0,
            settling_time_s=0.001,
            min_abs_tolerance=0.1,
            max_staleness_s=0.5,
        )
        monitor.add_reading(2.0, timestamp=1.000)
        monitor.add_reading(2.0, timestamp=1.002)  # span 2 ms > 1 ms
        self.assertTrue(monitor.is_stable(2.0, current_time=1.002))

    def test_huge_tolerance_pct(self):
        """Large tolerance percentage (e.g. 100%) permits large deviation."""
        monitor = StabilityMonitor(
            tolerance_pct=100.0,
            settling_time_s=1.0,
            min_abs_tolerance=0.1,
            max_staleness_s=0.5,
        )
        now = 1.0
        # Target = 10.0, 100% tolerance -> [0.0, 20.0]
        for i in range(25):
            monitor.add_reading(18.0, timestamp=now + i * 0.05)
        self.assertTrue(monitor.is_stable(10.0, current_time=now + 1.2))


if __name__ == "__main__":
    unittest.main()
