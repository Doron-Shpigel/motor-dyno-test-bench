"""
Calibration Settings module.

Pure Python container for dynamometer calibration parameters and app configuration.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CalibrationSettings:
    """
    Plain-data container for calibration settings and hardware conversion factors.
    """
    max_torque_nm: float = 5.0         # N·m -> DAC full scale (updated by calibration)
    rpm_per_count: float = 0.5         # RPM = adc_raw * rpm_per_count
    poll_interval_ms: int = 100        # control-loop tick interval in ms
    output_dir: str = field(default_factory=lambda: str(Path.home()))
    torque_per_count: float = 5.0 / (1023.0 - 512.0)
