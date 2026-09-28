"""
Shared, thread-safe data model for a single dyno run session.

All lists grow during a run and are consumed by the plot/logger.
Access is protected by a threading.Lock so the serial thread and
the GUI timer can both touch it safely.
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List


class RunState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    FINISHED = auto()
    ERROR = auto()


class RunMode(Enum):
    NONE = auto()
    PROFILE = auto()
    MANUAL = auto()


@dataclass
class Sample:
    """One recorded data point."""
    elapsed_s: float
    torque_nm: float
    rpm: float
    dac_raw: int        # 0-4095 value sent to MCP4725
    adc_raw: int        # 0-1023 raw reading from Arduino analog pin
    target_torque_nm: float = 0.0  # Commanded setpoint (N·m)


class DynoSession:
    """
    Accumulates samples for a single dyno run.

    Thread-safe: use append_sample() / get_snapshot() from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: List[Sample] = []
        self._start_time: float | None = None
        self.state: RunState = RunState.IDLE
        self.run_mode: RunMode = RunMode.NONE

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, mode: RunMode) -> None:
        with self._lock:
            self._samples.clear()
            self._start_time = time.perf_counter()
            self.state = RunState.RUNNING
            self.run_mode = mode

    def finish(self) -> None:
        with self._lock:
            self.state = RunState.FINISHED

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._start_time = None
            self.state = RunState.IDLE
            self.run_mode = RunMode.NONE

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def append_sample(self, sample: Sample) -> None:
        with self._lock:
            self._samples.append(sample)

    def elapsed_seconds(self) -> float:
        """Seconds since start(), or 0 if not started."""
        if self._start_time is None:
            return 0.0
        return time.perf_counter() - self._start_time

    # ------------------------------------------------------------------
    # Reading (returns copies — safe to use outside lock)
    # ------------------------------------------------------------------

    def get_snapshot(self) -> List[Sample]:
        """Return a shallow copy of all samples so far."""
        with self._lock:
            return list(self._samples)

    def sample_count(self) -> int:
        with self._lock:
            return len(self._samples)

    def last_sample(self) -> Sample | None:
        with self._lock:
            return self._samples[-1] if self._samples else None
