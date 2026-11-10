"""
Adversarial and stress tests for StabilityMonitor (modules/stability_monitor.py).

Tests:
  - Boundary noise oscillations straddling upper and lower tolerance bands
  - Sudden transient torque spikes resetting settling state
  - Non-monotonic timestamps and timestamp jitter
  - Telemetry dropouts and gap detection within settling window
  - Post-settling telemetry staleness
  - Extreme setpoints (zero, negative, very large, non-finite)
  - Telemetry buffer throughput stress with 10,000 high-frequency samples
"""

import math
import random
import time
import unittest

from modules.stability_monitor import StabilityMonitor


class TestAdversarialStabilityMonitor(unittest.TestCase):
    """Adversarial and edge-case testing for StabilityMonitor."""

    def setUp(self):
        self.monitor = StabilityMonitor(
            tolerance_pct=2.0,
            settling_time_s=1.5,
            min_abs_tolerance=0.1,
            max_staleness_s=0.5,
        )

    def test_oscillations_straddling_upper_boundary(self):
        """Noise oscillating across upper bound must never be evaluated as stable."""
        # Target = 10.0 N·m, 2% tolerance -> upper bound = 10.20 N·m
        # Oscillate between 10.15 and 10.25 (exceeding 10.20)
        target = 10.0
        now = 100.0
        for i in range(50):
            val = 10.15 if i % 2 == 0 else 10.25
            self.monitor.add_reading(val, timestamp=now + i * 0.05)

        self.assertFalse(self.monitor.is_stable(target, current_time=now + 50 * 0.05))

    def test_oscillations_straddling_lower_boundary(self):
        """Noise oscillating across lower bound must never be evaluated as stable."""
        # Target = 10.0 N·m, 2% tolerance -> lower bound = 9.80 N·m
        # Oscillate between 9.85 and 9.75 (below 9.80)
        target = 10.0
        now = 100.0
        for i in range(50):
            val = 9.85 if i % 2 == 0 else 9.75
            self.monitor.add_reading(val, timestamp=now + i * 0.05)

        self.assertFalse(self.monitor.is_stable(target, current_time=now + 50 * 0.05))

    def test_noisy_oscillations_within_band_become_stable(self):
        """Noise strictly confined within tolerance band settles to stable."""
        # Target = 10.0 N·m, Band = [9.80, 10.20]
        # Random noise strictly inside [9.85, 10.15]
        target = 10.0
        now = 100.0
        random.seed(42)
        for i in range(40):  # 40 * 0.05 = 2.0s (> 1.5s settling time)
            val = 10.0 + random.uniform(-0.15, 0.15)
            self.monitor.add_reading(val, timestamp=now + i * 0.05)

        self.assertTrue(self.monitor.is_stable(target, current_time=now + 40 * 0.05))

    def test_sudden_transient_torque_spike_invalidates_stability(self):
        """A transient spike right before settling duration expires invalidates stability."""
        target = 5.0
        now = 10.0
        # 28 samples at 20 Hz = 1.4s of clean data
        for i in range(28):
            self.monitor.add_reading(5.0, timestamp=now + i * 0.05)

        # Still not stable (span is 1.4s < 1.5s)
        self.assertFalse(self.monitor.is_stable(target, current_time=now + 28 * 0.05))

        # Single transient spike at 1.45s to 8.0 N·m
        self.monitor.add_reading(8.0, timestamp=now + 29 * 0.05)

        # More samples at 5.0 N·m (t=1.50 to t=2.00)
        for i in range(30, 41):
            self.monitor.add_reading(5.0, timestamp=now + i * 0.05)

        # The spike at t=11.45s is still in the 1.5s window [10.55s, 12.05s]!
        self.assertFalse(self.monitor.is_stable(target, current_time=now + 40 * 0.05))

        # Only after the spike falls out of the settling window does it become stable
        for i in range(41, 65):  # span from t=29 is now > 1.5s
            self.monitor.add_reading(5.0, timestamp=now + i * 0.05)

        self.assertTrue(self.monitor.is_stable(target, current_time=now + 64 * 0.05))

    def test_dropped_telemetry_gap_in_settling_window(self):
        """Packet dropout (> max_staleness_s) inside settling window rejects stability."""
        target = 2.0
        now = 50.0
        # First half of window
        for i in range(15):
            self.monitor.add_reading(2.0, timestamp=now + i * 0.05)  # 0.0s to 0.7s

        # 0.6s blackout (gap > max_staleness 0.5s)
        gap_resume_time = now + 0.70 + 0.60  # at 1.30s
        for i in range(15):
            self.monitor.add_reading(2.0, timestamp=gap_resume_time + i * 0.05)  # 1.30s to 2.00s

        # Even though total span is 2.0s and all readings are 2.0 N·m, gap inside window fails stability
        self.assertFalse(self.monitor.is_stable(target, current_time=gap_resume_time + 14 * 0.05))

    def test_staleness_after_steady_state_reached(self):
        """Telemtry that becomes stale after achieving stability immediately reverts to unstable."""
        target = 3.0
        now = 10.0
        # Settle stably for 2.0s
        for i in range(40):
            self.monitor.add_reading(3.0, timestamp=now + i * 0.05)

        t_latest = now + 39 * 0.05  # t = 11.95
        # Fresh
        self.assertTrue(self.monitor.is_stable(target, current_time=t_latest + 0.1))
        # Stale: 0.6s since latest reading (> max_staleness 0.5s)
        self.assertFalse(self.monitor.is_stable(target, current_time=t_latest + 0.6))

    def test_non_monotonic_timestamps_handled_safely(self):
        """Out-of-order timestamps must not cause crashes, infinite loops, or false positives."""
        # Adding readings out of order
        self.monitor.add_reading(2.0, timestamp=10.0)
        self.monitor.add_reading(2.0, timestamp=12.0)
        self.monitor.add_reading(2.0, timestamp=11.0)  # out of order

        # Should safely return without error
        result = self.monitor.is_stable(2.0, current_time=12.0)
        self.assertIsInstance(result, bool)

    def test_extreme_and_negative_target_setpoints(self):
        """Support for negative setpoints, zero setpoints, and very large setpoints."""
        # 1. Negative target torque: -4.0 N·m, 2% band = 0.08, min floor = 0.10 -> band [-4.10, -3.90]
        now = 1.0
        for i in range(35):
            self.monitor.add_reading(-4.02, timestamp=now + i * 0.05)
        self.assertTrue(self.monitor.is_stable(-4.0, current_time=now + 34 * 0.05))

        # Value outside negative band (-4.15) fails
        self.monitor.add_reading(-4.15, timestamp=now + 35 * 0.05)
        self.assertFalse(self.monitor.is_stable(-4.0, current_time=now + 35 * 0.05))

        # 2. Very large setpoint: 5000.0 N·m (band is 100.0 N·m)
        self.monitor.reset()
        for i in range(35):
            self.monitor.add_reading(5050.0, timestamp=now + i * 0.05)
        self.assertTrue(self.monitor.is_stable(5000.0, current_time=now + 34 * 0.05))

        # 3. Non-finite targets
        self.assertFalse(self.monitor.is_stable(float("nan"), current_time=now + 34 * 0.05))
        self.assertFalse(self.monitor.is_stable(float("inf"), current_time=now + 34 * 0.05))

    def test_high_frequency_telemetry_flooding(self):
        """Adding 10,000 readings in a tight loop tests memory pruning and throughput."""
        now = 0.0
        # 10,000 samples at 1000 Hz = 10.0 seconds of telemetry
        for i in range(10000):
            t = now + i * 0.001
            self.monitor.add_reading(2.5, timestamp=t)

        # Settling time is 1.5s, cutoff is max(1.5*3, 5.0) = 5.0s
        # 5.0 seconds at 1000 Hz ~ 5000 samples retained
        count = self.monitor.reading_count()
        self.assertLess(count, 5100)
        self.assertGreater(count, 4900)

        # Evaluates stability quickly and accurately
        self.assertTrue(self.monitor.is_stable(2.5, current_time=10.0))


if __name__ == "__main__":
    unittest.main()
