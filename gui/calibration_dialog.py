"""
Calibration & Settings Dialog.

Stores user-configurable conversion factors:
  - max_torque_nm   : torque corresponding to full DAC output (4095)
  - rpm_per_count   : RPM = adc_raw * rpm_per_count
  - poll_interval_ms: how often to tick the control loop (ms)
  - output_dir      : directory for log CSV files
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class CalibrationSettings:
    """Plain-data container — pass around instead of individual floats."""

    def __init__(self) -> None:
        self.max_torque_nm: float   = 50.0   # N·m → DAC full scale
        self.rpm_per_count: float   = 0.5    # RPM = adc_raw * rpm_per_count
        self.poll_interval_ms: int  = 100    # control-loop tick (ms)
        self.output_dir: str        = str(Path.home())


class CalibrationDialog(QDialog):
    """
    Modal dialog for editing CalibrationSettings in-place.

    Usage:
        dlg = CalibrationDialog(settings, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # settings has been updated in-place
    """

    def __init__(self, settings: CalibrationSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calibration & Settings")
        self.setMinimumWidth(400)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- Torque calibration ----
        torque_group = QGroupBox("Torque / DAC Calibration")
        form1 = QFormLayout(torque_group)

        self._max_torque_spin = QDoubleSpinBox()
        self._max_torque_spin.setRange(0.1, 10000.0)
        self._max_torque_spin.setDecimals(2)
        self._max_torque_spin.setSuffix("  N·m")
        self._max_torque_spin.setValue(self._settings.max_torque_nm)
        form1.addRow("Max torque (DAC=4095):", self._max_torque_spin)

        note1 = QLabel(
            "DAC value = (torque / max_torque) × 4095\n"
            "MCP4725 address: 0x60 (ADDR pin to GND) — edit .ino to change."
        )
        note1.setStyleSheet("color: gray; font-size: 11px;")
        note1.setWordWrap(True)
        form1.addRow(note1)
        layout.addWidget(torque_group)

        # ---- Speed calibration ----
        speed_group = QGroupBox("Speed (RPM) Calibration")
        form2 = QFormLayout(speed_group)

        self._rpm_per_count_spin = QDoubleSpinBox()
        self._rpm_per_count_spin.setRange(0.001, 100000.0)
        self._rpm_per_count_spin.setDecimals(4)
        self._rpm_per_count_spin.setValue(self._settings.rpm_per_count)
        form2.addRow("RPM per ADC count:", self._rpm_per_count_spin)

        note2 = QLabel(
            "RPM = ADC_raw (0–1023) × rpm_per_count\n"
            "Measure at a known speed to derive this factor."
        )
        note2.setStyleSheet("color: gray; font-size: 11px;")
        note2.setWordWrap(True)
        form2.addRow(note2)
        layout.addWidget(speed_group)

        # ---- Control loop ----
        loop_group = QGroupBox("Control Loop")
        form3 = QFormLayout(loop_group)

        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(20, 2000)
        self._poll_spin.setSingleStep(10)
        self._poll_spin.setSuffix("  ms")
        self._poll_spin.setValue(self._settings.poll_interval_ms)
        form3.addRow("Tick interval:", self._poll_spin)
        layout.addWidget(loop_group)

        # ---- Output directory ----
        out_group = QGroupBox("Log Output")
        out_layout = QHBoxLayout(out_group)
        self._out_edit = QLineEdit(self._settings.output_dir)
        self._out_edit.setReadOnly(True)
        out_layout.addWidget(self._out_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(browse_btn)
        layout.addWidget(out_group)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self._out_edit.text()
        )
        if d:
            self._out_edit.setText(d)

    def _on_accept(self) -> None:
        self._settings.max_torque_nm    = self._max_torque_spin.value()
        self._settings.rpm_per_count    = self._rpm_per_count_spin.value()
        self._settings.poll_interval_ms = self._poll_spin.value()
        self._settings.output_dir       = self._out_edit.text()
        self.accept()
