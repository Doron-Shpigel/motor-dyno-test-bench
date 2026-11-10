"""
Unit and regression tests for StabilityMonitor (modules/stability_monitor.py).

Tests:
  - Property validation & parameter setters (rejecting non-finite, negative, zero values)
  - Memory pruning of old readings in add_reading
  - Exact tolerance band calculation and floating point margin behavior
  - Staleness detection (now - latest_time > max_staleness_s)
  - Inter-sample gap detection during settling window
  - Buffer span requirements
  - Buffer reset and reading count
"""

import math
import time
import unittest

from modules.stability_monitor import StabilityMonitor


class TestStabilityMonitorParameters(unittest.TestCase):
    """Test parameter validation, defaults, and property setters."""

    def setUp(self):
        self.monitor = StabilityMonitor()

    def test_default_values(self):
        self.assertAlmostEqual(self.monitor.tolerance_pct, 2.0)
        self.assertAlmostEqual(self.monitor.settling_time_s, 1.5)
        self.assertAlmostEqual(self.monitor.min_abs_tolerance, 0.1)
        self.assertAlmostEqual(self.monitor.max_staleness_s, 0.5)

    def test_tolerance_pct_valid(self):
        self.monitor.tolerance_pct = 1.0
        self.assertAlmostEqual(self.monitor.tolerance_pct, 1.0)
        self.monitor.tolerance_pct = 10.5
        self.assertAlmostEqual(self.monitor.tolerance_pct, 10.5)

    def test_tolerance_pct_invalid(self):
        for invalid in [0.0, -1.0, -0.001, float("nan"), float("inf"), float("-inf")]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.monitor.tolerance_pct = invalid

    def test_settling_time_valid(self):
        self.monitor.settling_time_s = 0.5
        self.assertAlmostEqual(self.monitor.settling_time_s, 0.5)
        self.monitor.settling_time_s = 5.0
        self.assertAlmostEqual(self.monitor.settling_time_s, 5.0)

    def test_settling_time_invalid(self):
        for invalid in [0.0, -0.5, -10.0, float("nan"), float("inf"), float("-inf")]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.monitor.settling_time_s = invalid

    def test_min_abs_tolerance_valid(self):
        self.monitor.min_abs_tolerance = 0.0
        self.assertAlmostEqual(self.monitor.min_abs_tolerance, 0.0)
        self.monitor.min_abs_tolerance = 0.25
        self.assertAlmostEqual(self.monitor.min_abs_tolerance, 0.25)

    def test_min_abs_tolerance_invalid(self):
        for invalid in [-0.01, -1.0, float("nan"), float("inf"), float("-inf")]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.monitor.min_abs_tolerance = invalid

    def test_max_staleness_valid(self):
        self.monitor.max_staleness_s = 0.1
        self.assertAlmostEqual(self.monitor.max_staleness_s, 0.1)
        self.monitor.max_staleness_s = 2.0
        self.assertAlmostEqual(self.monitor.max_staleness_s, 2.0)

    def test_max_staleness_invalid(self):
        for invalid in [0.0, -0.1, -1.0, float("nan"), float("inf"), float("-inf")]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.monitor.max_staleness_s = invalid

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            StabilityMonitor(tolerance_pct=-1.0)
        with self.assertRaises(ValueError):
            StabilityMonitor(settling_time_s=0.0)
        with self.assertRaises(ValueError):
            StabilityMonitor(min_abs_tolerance=-0.5)
        with self.assertRaises(ValueError):
            StabilityMonitor(max_staleness_s=-0.1)

    def test_set_and_update_parameters(self):
        self.monitor.set_parameters(tolerance_pct=3.0, settling_time_s=2.0, min_abs_tolerance=0.2)
        self.assertAlmostEqual(self.monitor.tolerance_pct, 3.0)
        self.assertAlmostEqual(self.monitor.settling_time_s, 2.0)
        self.assertAlmostEqual(self.monitor.min_abs_tolerance, 0.2)

        # Alias update_parameters
        self.monitor.update_parameters(tolerance_pct=4.0)
        self.assertAlmostEqual(self.monitor.tolerance_pct, 4.0)
        self.assertAlmostEqual(self.monitor.settling_time_s, 2.0)  # unchanged


class TestStabilityMonitorBufferAndPruning(unittest.TestCase):
    """Test buffer operations, memory pruning, and reading counts."""

    def test_memory_pruning(self):
        monitor = StabilityMonitor(settling_time_s=1.0)  # prune cutoff = t - max(3*1, 5) = t - 5.0
        # Add readings at t=0.0 to 10.0 every 1.0 second
        for i in range(11):
            monitor.add_reading(2.0, timestamp=float(i))

        # At t=10.0, cutoff is 10.0 - 5.0 = 5.0
        # Readings strictly < 5.0 (i.e. 0.0, 1.0, 2.0, 3.0, 4.0) must be pruned.
        # Readings >= 5.0 (5.0, 6.0, 7.0, 8.0, 9.0, 10.0) remain -> 6 readings.
        self.assertEqual(monitor.reading_count(), 6)
        oldest_t, _ = monitor._readings[0]
        self.assertGreaterEqual(oldest_t, 5.0)

    def test_large_history_bounded_memory(self):
        monitor = StabilityMonitor(settling_time_s=1.5)  # cutoff = 5.0s
        for i in range(1000):
            monitor.add_reading(2.0, timestamp=i * 0.05)  # 20 Hz for 50 seconds

        # Only last ~5 seconds should remain (approx 100-110 readings)
        self.assertLess(monitor.reading_count(), 120)
        self.assertGreater(monitor.reading_count(), 90)

    def test_default_timestamp_uses_perf_counter(self):
        monitor = StabilityMonitor()
        t_before = time.perf_counter()
        monitor.add_reading(2.0)
        t_after = time.perf_counter()
        self.assertEqual(monitor.reading_count(), 1)
        t_sample, val = monitor._readings[0]
        self.assertGreaterEqual(t_sample, t_before)
        self.assertLessEqual(t_sample, t_after)
        self.assertAlmostEqual(val, 2.0)

    def test_reset_clears_buffer(self):
        monitor = StabilityMonitor()
        monitor.add_reading(1.5, timestamp=1.0)
        monitor.add_reading(1.5, timestamp=2.0)
        self.assertEqual(monitor.reading_count(), 2)

        monitor.reset()
        self.assertEqual(monitor.reading_count(), 0)
        self.assertFalse(monitor.is_stable(1.5, current_time=2.0))


class TestStabilityMonitorEvaluation(unittest.TestCase):
    """Test is_stable steady-state detection logic."""

    def setUp(self):
        self.monitor = StabilityMonitor(
            tolerance_pct=2.0,
            settling_time_s=1.0,
            min_abs_tolerance=0.1,
            max_staleness_s=0.5,
        )

    def test_empty_buffer_not_stable(self):
        self.assertFalse(self.monitor.is_stable(2.0))

    def test_non_finite_target_torque(self):
        self.monitor.add_reading(2.0, timestamp=1.0)
        self.assertFalse(self.monitor.is_stable(float("nan"), current_time=1.0))
        self.assertFalse(self.monitor.is_stable(float("inf"), current_time=1.0))
        self.assertFalse(self.monitor.is_stable(float("-inf"), current_time=1.0))

    def test_insufficient_time_span(self):
        # Settling time is 1.0s, but readings only span 0.5s
        for t in [1.0, 1.2, 1.5]:
            self.monitor.add_reading(2.0, timestamp=t)
        self.assertFalse(self.monitor.is_stable(2.0, current_time=1.5))

    def test_stable_steady_state(self):
        # 20 Hz readings from t=0.0 to t=1.2 (span 1.2s > settling_time 1.0s)
        for i in range(25):
            t = i * 0.05
            self.monitor.add_reading(2.0, timestamp=t)
        self.assertTrue(self.monitor.is_stable(2.0, current_time=1.2))

    def test_staleness_detection(self):
        for i in range(25):
            t = i * 0.05  # up to 1.2s
            self.monitor.add_reading(2.0, timestamp=t)

        # At t=1.2, fresh
        self.assertTrue(self.monitor.is_stable(2.0, current_time=1.2))
        # At t=1.6, elapsed since latest is 0.4s (< max_staleness 0.5s)
        self.assertTrue(self.monitor.is_stable(2.0, current_time=1.6))
        # At t=1.8, elapsed since latest is 0.6s (> max_staleness 0.5s) -> stale!
        self.assertFalse(self.monitor.is_stable(2.0, current_time=1.8))

    def test_inter_sample_gap_detection(self):
        # Create readings with a gap > max_staleness (0.5s) inside settling window
        # Settling window spans [0.5, 1.5]
        self.monitor.add_reading(2.0, timestamp=0.0)
        self.monitor.add_reading(2.0, timestamp=0.5)
        # Gap of 0.6s
        self.monitor.add_reading(2.0, timestamp=1.1)
        self.monitor.add_reading(2.0, timestamp=1.5)

        self.assertFalse(self.monitor.is_stable(2.0, current_time=1.5))

    def test_tolerance_band_percentage_vs_floor(self):
        # Target = 10.0 N·m: 2% is 0.2 N·m (> min_abs_tolerance 0.1 N·m)
        # Band is [9.80, 10.20]
        # At 10.19 -> stable
        m1 = StabilityMonitor(tolerance_pct=2.0, settling_time_s=1.0, min_abs_tolerance=0.1)
        for i in range(25):
            m1.add_reading(10.19, timestamp=i * 0.05)
        self.assertTrue(m1.is_stable(10.0, current_time=1.2))

        # At 10.25 -> unstable
        m2 = StabilityMonitor(tolerance_pct=2.0, settling_time_s=1.0, min_abs_tolerance=0.1)
        for i in range(25):
            m2.add_reading(10.25, timestamp=i * 0.05)
        self.assertFalse(m2.is_stable(10.0, current_time=1.2))

    def test_min_abs_tolerance_at_zero_torque(self):
        # Target = 0.0 N·m: 2% of 0 is 0.0, so min_abs_tolerance (0.1 N·m) must be used!
        # Band is [-0.10, +0.10]
        for i in range(25):
            self.monitor.add_reading(0.08, timestamp=i * 0.05)
        self.assertTrue(self.monitor.is_stable(0.0, current_time=1.2))

        # Value of 0.15 exceeds min_abs_tolerance
        self.monitor.add_reading(0.15, timestamp=1.25)
        self.assertFalse(self.monitor.is_stable(0.0, current_time=1.25))

    def test_exact_boundary_floating_point_margin(self):
        # Target = 2.0, min_abs_tolerance = 0.1, band = 0.1.
        # Boundary = 2.10. Due to 1e-9 margin, 2.10 and 2.10000000001 are within bounds.
        for i in range(25):
            self.monitor.add_reading(2.10, timestamp=i * 0.05)
        self.assertTrue(self.monitor.is_stable(2.0, current_time=1.2))

        # Value clearly outside boundary (2.10001) must fail
        self.monitor.add_reading(2.10001, timestamp=1.25)
        self.assertFalse(self.monitor.is_stable(2.0, current_time=1.25))


if __name__ == "__main__":
    unittest.main()
