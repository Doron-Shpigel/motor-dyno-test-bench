"""
CSV Logger module.

Opens an output CSV file at the start of a run and appends one row
per sample.  Call close() (or use as a context manager) when the
run is over.

Output columns:
    elapsed_s, torque_nm, rpm, dac_raw, adc_raw
"""

import csv
import datetime
from pathlib import Path

from modules.data_model import Sample


FIELDNAMES = ["elapsed_s", "torque_nm", "rpm", "dac_raw", "adc_raw"]


class CSVLogger:
    """
    Writes dyno samples to a CSV file.

    Usage
    -----
        logger = CSVLogger()
        path = logger.open()          # auto-generates filename
        logger.write(sample)
        logger.close()

    Or:
        with CSVLogger() as logger:
            path = logger.open(output_dir)
            ...
    """

    def __init__(self) -> None:
        self._file = None
        self._writer: csv.DictWriter | None = None
        self._path: Path | None = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def open_temp(self) -> Path:
        """
        Create a new temporary log file `temp_run.csv` in the current directory.

        Returns the full path of the created file.
        Raises RuntimeError if a file is already open.
        """
        if self._file is not None:
            raise RuntimeError("A log file is already open. Call close() first.")

        self._path = Path("temp_run.csv")

        self._file = self._path.open("w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()
        return self._path

    def save_to(self, dest_dir: str | Path, timestamp: str) -> Path | None:
        """
        Move the temp file to the final destination with the timestamp.
        """
        if not self._path or not self._path.exists():
            return None
            
        if self._file is not None:
            self.close()
            
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_path = dest_dir / f"dyno_log_{timestamp}.csv"
        
        import shutil
        shutil.move(str(self._path), str(final_path))
        self._path = final_path
        return final_path

    def open_explicit(self, filepath: str | Path) -> Path:
        """Open a specific file path instead of auto-generating one."""
        if self._file is not None:
            raise RuntimeError("A log file is already open. Call close() first.")

        self._path = Path(filepath)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()
        return self._path

    def close(self) -> None:
        """Flush and close the log file."""
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write(self, sample: Sample) -> None:
        """
        Append a single sample row to the log file.

        Safe to call from any thread as long as only one thread writes.
        """
        if self._writer is None:
            raise RuntimeError("Log file is not open. Call open() first.")
        self._writer.writerow(
            {
                "elapsed_s": f"{sample.elapsed_s:.4f}",
                "torque_nm": f"{sample.torque_nm:.4f}",
                "rpm": f"{sample.rpm:.2f}",
                "dac_raw": sample.dac_raw,
                "adc_raw": sample.adc_raw,
            }
        )
        self._file.flush()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def is_open(self) -> bool:
        return self._file is not None
