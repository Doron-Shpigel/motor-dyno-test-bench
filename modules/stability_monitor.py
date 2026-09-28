"""
Stability Monitor module.

Monitors physical torque telemetry from the dynamometer test bench to detect
when the system has achieved steady state at a target torque setpoint.
"""

from collections import deque
import math
import time
from typing import Deque, Tuple


class StabilityMonitor:
    """
    Evaluates whether measured torque has settled at a target setpoint.

    Criteria:
      Physical measured torque must stay continuously within ±tolerance%
      of the target setpoint for at least settling_time_s seconds.
    """

    def __init__(
        self,
        tolerance_pct: float = 2.0,
        settling_time_s: float = 1.5,
        min_abs_tolerance: float = 0.1,
        max_staleness_s: float = 0.5,
    ) -> None:
        self.set_parameters(
            tolerance_pct=tolerance_pct,
            settling_time_s=settling_time_s,
            min_abs_tolerance=min_abs_tolerance,
        )
        if not math.isfinite(max_staleness_s) or max_staleness_s <= 0:
            raise ValueError("max_staleness_s must be positive and finite")
        self._max_staleness_s = float(max_staleness_s)
        self._readings: Deque[Tuple[float, float]] = deque()

    # ------------------------------------------------------------------
    # Properties & Parameter Configuration
    # ------------------------------------------------------------------

    @property
    def tolerance_pct(self) -> float:
        """Allowed steady-state tolerance percentage around setpoint."""
        return self._tolerance_pct

    @tolerance_pct.setter
    def tolerance_pct(self, val: float) -> None:
        self.set_parameters(tolerance_pct=val)

    @property
    def settling_time_s(self) -> float:
        """Minimum required continuous duration within tolerance (seconds)."""
        return self._settling_time_s

    @settling_time_s.setter
    def settling_time_s(self, val: float) -> None:
        self.set_parameters(settling_time_s=val)

    @property
    def min_abs_tolerance(self) -> float:
        """Minimum absolute tolerance floor in N·m (prevents zero-band at 0 N·m)."""
        return self._min_abs_tolerance

    @min_abs_tolerance.setter
    def min_abs_tolerance(self, val: float) -> None:
        self.set_parameters(min_abs_tolerance=val)

    @property
    def max_staleness_s(self) -> float:
        """Maximum age of latest sample before telemetry is considered stale."""
        return self._max_staleness_s

    @max_staleness_s.setter
    def max_staleness_s(self, val: float) -> None:
        if not math.isfinite(val) or val <= 0:
            raise ValueError("max_staleness_s must be positive and finite")
        self._max_staleness_s = float(val)

    def set_parameters(
        self,
        tolerance_pct: float | None = None,
        settling_time_s: float | None = None,
        min_abs_tolerance: float | None = None,
    ) -> None:
        """Update stability thresholds dynamically."""
        if tolerance_pct is not None:
            if not math.isfinite(tolerance_pct) or tolerance_pct <= 0:
                raise ValueError("tolerance_pct must be positive and finite")
            self._tolerance_pct = float(tolerance_pct)

        if settling_time_s is not None:
            if not math.isfinite(settling_time_s) or settling_time_s <= 0:
                raise ValueError("settling_time_s must be positive and finite")
            self._settling_time_s = float(settling_time_s)

        if min_abs_tolerance is not None:
            if not math.isfinite(min_abs_tolerance) or min_abs_tolerance < 0:
                raise ValueError("min_abs_tolerance cannot be negative and must be finite")
            self._min_abs_tolerance = float(min_abs_tolerance)

    def update_parameters(
        self,
        tolerance_pct: float | None = None,
        settling_time_s: float | None = None,
        min_abs_tolerance: float | None = None,
    ) -> None:
        """Alias for set_parameters."""
        self.set_parameters(
            tolerance_pct=tolerance_pct,
            settling_time_s=settling_time_s,
            min_abs_tolerance=min_abs_tolerance,
        )

    # ------------------------------------------------------------------
    # Telemetry Ingestion & State Evaluation
    # ------------------------------------------------------------------

    def add_reading(self, torque: float, timestamp: float | None = None) -> None:
        """
        Record a measured torque reading.

        Parameters
        ----------
        torque : float
            Physical measured torque in N·m.
        timestamp : float | None
            Timestamp in seconds. Defaults to time.perf_counter().
        """
        if timestamp is None:
            timestamp = time.perf_counter()

        t = float(timestamp)
        val = float(torque)
        self._readings.append((t, val))

        # Memory pruning: retain readings within max(3 * settling_time_s, 5.0)
        prune_cutoff = t - max(self._settling_time_s * 3.0, 5.0)
        while self._readings and self._readings[0][0] < prune_cutoff:
            self._readings.popleft()

    def is_stable(self, target_torque: float, current_time: float | None = None) -> bool:
        """
        Evaluate if measured torque has settled at target_torque.

        Returns True if and only if:
        1. Telemetry buffer is not empty and latest reading is not stale.
        2. Readings in the buffer span at least settling_time_s.
        3. All readings in the window [t_latest - settling_time_s, t_latest]
           fall within [target_torque - band, target_torque + band].
        4. Inter-sample gaps within the settling window do not exceed max_staleness_s.
        """
        if not self._readings:
            return False

        if not math.isfinite(target_torque):
            return False

        latest_time, _ = self._readings[-1]
        now = float(current_time) if current_time is not None else time.perf_counter()

        # Telemetry staleness check
        if (now - latest_time) > self._max_staleness_s:
            return False

        # Total buffer time span check
        oldest_time, _ = self._readings[0]
        if (latest_time - oldest_time) < self._settling_time_s:
            return False

        # Compute tolerance band
        target = float(target_torque)
        band = max(abs(target) * (self._tolerance_pct / 100.0), self._min_abs_tolerance)
        # 1e-9 margin prevents binary floating-point representation rounding errors on exact boundaries
        lower_bound = target - band - 1e-9
        upper_bound = target + band + 1e-9

        # Continuous tolerance band check across [latest_time - settling_time_s, latest_time]
        # and verify inter-sample gaps do not exceed max_staleness_s
        window_start = latest_time - self._settling_time_s - 1e-9
        last_t = latest_time
        for t, val in reversed(self._readings):
            if (last_t - t) > self._max_staleness_s:
                return False
            if t < window_start:
                break
            if not (lower_bound <= val <= upper_bound):
                return False
            last_t = t
            if last_t <= (latest_time - self._settling_time_s + 1e-9):
                break

        return True

    def reset(self) -> None:
        """Clear reading history when stepping to a new setpoint."""
        self._readings.clear()

    def reading_count(self) -> int:
        """Return the current number of readings stored in the buffer."""
        return len(self._readings)
