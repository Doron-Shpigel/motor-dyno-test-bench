"""
Settings Tab.

Provides three sections:
  1. Hardware PID Parameters — read/write Kp, Ki, Kd stored in Arduino EEPROM.
  2. Software Stability Monitor — configure tolerance and settling-time thresholds.
  3. Calibration & Settings — RPM factor, loop interval, and Max Torque Calibration.
"""

import math
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CalibrationSettings:
    """Plain-data container — pass around instead of individual floats."""
    def __init__(self) -> None:
        self.max_torque_nm: float   = 5.0    # N·m → DAC full scale (updated by calibration)
        self.rpm_per_count: float   = 0.5    # RPM = adc_raw * rpm_per_count
        self.poll_interval_ms: int  = 100    # control-loop tick (ms)
        self.output_dir: str        = str(Path.home())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section_title(text: str) -> QLabel:
    """Bold section heading."""
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(11)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setStyleSheet("color: #89b4fa;")
    return lbl


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet("color: #45475a;")
    return line


def _read_only_edit(placeholder: str = "—") -> QLineEdit:
    edit = QLineEdit(placeholder)
    edit.setReadOnly(True)
    edit.setStyleSheet(
        "background: #181825; color: #a6adc8; border: 1px solid #313244;"
        " border-radius: 4px; padding: 3px 6px;"
    )
    edit.setFixedWidth(110)
    return edit


def _editable_edit(placeholder: str = "0.000") -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setFixedWidth(110)
    return edit


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class SettingsTab(QWidget):
    """
    'Settings' tab widget replacing the old PID tab and Calibration Dialog.
    """

    sig_read_pid = pyqtSignal()
    sig_set_pid = pyqtSignal(float, float, float)
    sig_send_command = pyqtSignal(str)
    sig_update_stability_params = pyqtSignal(float, float)
    sig_update_calibration = pyqtSignal()
    sig_start_torque_calibration = pyqtSignal()
    sig_finish_torque_calibration = pyqtSignal()

    def __init__(
        self,
        calibration: CalibrationSettings,
        parent: QWidget | None = None,
        command_sender: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._calibration = calibration
        self._command_sender = command_sender
        self._last_error: str | None = None
        self._is_calibrating = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(18)

        # 1. Hardware PID
        root.addWidget(self._build_hardware_pid_section())
        root.addWidget(_separator())
        # 2. Stability Monitor
        root.addWidget(self._build_stability_monitor_section())
        root.addWidget(_separator())
        # 3. Calibration & App Settings
        root.addWidget(self._build_calibration_section())
        
        root.addStretch(1)

    # ── Section 1: Hardware PID (Arduino EEPROM) ─────────────────────────

    def _build_hardware_pid_section(self) -> QGroupBox:
        group = QGroupBox()
        outer = QVBoxLayout(group)
        outer.setSpacing(12)
        outer.addWidget(_section_title("Arduino EEPROM PID Settings"))

        # ---- Current stored values (read-only) ----
        stored_grid = QGridLayout()
        stored_grid.setHorizontalSpacing(20)
        stored_grid.setVerticalSpacing(6)
        for col, text in enumerate(["Parameter", "Stored value"]):
            h = QLabel(text)
            h.setStyleSheet("font-weight: bold; color: #cdd6f4;")
            stored_grid.addWidget(h, 0, col)

        pid_labels = [("Kp  (Proportional)", "kp"), ("Ki  (Integral)", "ki"), ("Kd  (Derivative)", "kd")]
        self._stored: dict[str, QLineEdit] = {}
        for row, (display, key) in enumerate(pid_labels, start=1):
            stored_grid.addWidget(QLabel(display), row, 0)
            edit = _read_only_edit("—")
            self._stored[key] = edit
            stored_grid.addWidget(edit, row, 1)

        outer.addLayout(stored_grid)

        # ---- New values (editable) ----
        new_grid = QGridLayout()
        new_grid.setHorizontalSpacing(20)
        new_grid.setVerticalSpacing(6)
        for col, text in enumerate(["Parameter", "New value"]):
            h = QLabel(text)
            h.setStyleSheet("font-weight: bold; color: #cdd6f4;")
            new_grid.addWidget(h, 0, col)

        self._inputs: dict[str, QLineEdit] = {}
        for row, (display, key) in enumerate(pid_labels, start=1):
            new_grid.addWidget(QLabel(display), row, 0)
            edit = _editable_edit("0.000")
            self._inputs[key] = edit
            new_grid.addWidget(edit, row, 1)

        outer.addLayout(new_grid)

        self._feedback_label = QLabel("")
        outer.addWidget(self._feedback_label)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        self._read_btn = QPushButton("Read from Arduino")
        self._read_btn.clicked.connect(self._on_read_from_arduino)
        self._save_btn = QPushButton("Save to Arduino")
        self._save_btn.clicked.connect(self._on_save_to_arduino)
        for btn in (self._read_btn, self._save_btn):
            btn.setMinimumWidth(160)
        btn_row.addWidget(self._read_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        return group

    # ── Section 2: Software Stability Monitor ────────────────────────────

    def _build_stability_monitor_section(self) -> QGroupBox:
        group = QGroupBox()
        outer = QVBoxLayout(group)
        outer.setSpacing(12)
        outer.addWidget(_section_title("Steady-State Settling Parameters"))

        params_grid = QGridLayout()
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0.1, 50.0)
        self._tolerance_spin.setValue(2.0)
        self._tolerance_spin.setSuffix("  %")
        params_grid.addWidget(QLabel("Tolerance (%):"), 0, 0)
        params_grid.addWidget(self._tolerance_spin, 0, 1)

        self._settling_spin = QDoubleSpinBox()
        self._settling_spin.setRange(0.1, 60.0)
        self._settling_spin.setValue(1.5)
        self._settling_spin.setSuffix("  s")
        params_grid.addWidget(QLabel("Settling Time (s):"), 1, 0)
        params_grid.addWidget(self._settling_spin, 1, 1)
        outer.addLayout(params_grid)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Current Status:"))
        self._status_label = QLabel("WAITING")
        self._status_label.setStyleSheet("background: #313244; color: #f9e2af; padding: 4px; font-weight: bold;")
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        outer.addLayout(status_row)

        btn_row = QHBoxLayout()
        self._update_stab_btn = QPushButton("Update Software Parameters")
        self._update_stab_btn.clicked.connect(self._on_update_software_params)
        btn_row.addWidget(self._update_stab_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        return group

    # ── Section 3: Calibration & Settings ────────────────────────────

    def _build_calibration_section(self) -> QGroupBox:
        group = QGroupBox()
        outer = QVBoxLayout(group)
        outer.setSpacing(12)
        outer.addWidget(_section_title("Calibration & App Settings"))

        # App Settings Form
        form = QFormLayout()
        
        self._rpm_per_count_spin = QDoubleSpinBox()
        self._rpm_per_count_spin.setRange(0.001, 100000.0)
        self._rpm_per_count_spin.setDecimals(4)
        self._rpm_per_count_spin.setValue(self._calibration.rpm_per_count)
        self._rpm_per_count_spin.valueChanged.connect(self._on_calibration_changed)
        form.addRow("RPM per ADC count:", self._rpm_per_count_spin)

        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(20, 2000)
        self._poll_spin.setSingleStep(10)
        self._poll_spin.setSuffix("  ms")
        self._poll_spin.setValue(self._calibration.poll_interval_ms)
        self._poll_spin.valueChanged.connect(self._on_calibration_changed)
        form.addRow("Tick interval:", self._poll_spin)
        
        out_layout = QHBoxLayout()
        self._out_edit = QLineEdit(self._calibration.output_dir)
        self._out_edit.setReadOnly(True)
        out_layout.addWidget(self._out_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(browse_btn)
        form.addRow("Log Output Dir:", out_layout)
        
        outer.addLayout(form)
        outer.addWidget(_separator())
        
        # Torque Sensor Calibration
        outer.addWidget(QLabel("<b>Max Torque Calibration Procedure</b>"))
        desc = QLabel(
            "This will activate the Torque Sensor, send maximum power (DAC=4095) to the brake, "
            "and measure the highest torque value as you apply manual force. Max value will be mapped to 5 N·m."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 11px;")
        outer.addWidget(desc)

        cal_row = QHBoxLayout()
        self._cal_start_btn = QPushButton("Start Torque Calibration")
        self._cal_start_btn.clicked.connect(self._on_start_calibration)
        self._cal_finish_btn = QPushButton("Finish Calibration")
        self._cal_finish_btn.setEnabled(False)
        self._cal_finish_btn.clicked.connect(self._on_finish_calibration)
        
        self._cal_status = QLabel("Ready")
        
        cal_row.addWidget(self._cal_start_btn)
        cal_row.addWidget(self._cal_finish_btn)
        cal_row.addWidget(self._cal_status)
        cal_row.addStretch(1)
        outer.addLayout(cal_row)

        return group

    # ------------------------------------------------------------------
    # Action slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", self._out_edit.text())
        if d:
            self._out_edit.setText(d)
            self._calibration.output_dir = d
            self.sig_update_calibration.emit()

    @pyqtSlot()
    def _on_calibration_changed(self) -> None:
        self._calibration.rpm_per_count = self._rpm_per_count_spin.value()
        self._calibration.poll_interval_ms = self._poll_spin.value()
        self.sig_update_calibration.emit()

    @pyqtSlot()
    def _on_start_calibration(self) -> None:
        self._is_calibrating = True
        self._cal_start_btn.setEnabled(False)
        self._cal_finish_btn.setEnabled(True)
        self._cal_status.setText("Calibrating... Apply force now.")
        self.sig_start_torque_calibration.emit()

    @pyqtSlot()
    def _on_finish_calibration(self) -> None:
        self._is_calibrating = False
        self._cal_start_btn.setEnabled(True)
        self._cal_finish_btn.setEnabled(False)
        self._cal_status.setText("Calibration finished. Saved as 5 N·m.")
        self.sig_finish_torque_calibration.emit()

    @pyqtSlot()
    def _on_read_from_arduino(self) -> None:
        self.sig_read_pid.emit()
        self.sig_send_command.emit("<GET_PID>")
        if self._command_sender is not None:
            self._command_sender("<GET_PID>")

    @pyqtSlot()
    def _on_save_to_arduino(self) -> None:
        vals = self.validate_inputs()
        if vals is None:
            return
        kp, ki, kd = vals
        cmd = f"<SET_PID:{kp:.4f},{ki:.4f},{kd:.4f}>"
        self.sig_set_pid.emit(kp, ki, kd)
        self.sig_send_command.emit(cmd)
        if self._command_sender is not None:
            self._command_sender(cmd)

    @pyqtSlot()
    def _on_update_software_params(self) -> None:
        tolerance = self._tolerance_spin.value()
        settling_time = self._settling_spin.value()
        self.sig_update_stability_params.emit(tolerance, settling_time)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_stored_values(self, kp: float, ki: float, kd: float) -> None:
        for key, val in (("kp", kp), ("ki", ki), ("kd", kd)):
            if key in self._stored:
                if math.isfinite(val):
                    self._stored[key].setText(f"{val:.4f}")
                else:
                    self._stored[key].setText("ERR")

    def set_stability_status(self, stable: bool) -> None:
        if stable:
            self._status_label.setText("STABLE")
            self._status_label.setStyleSheet("background: #1e4a2a; color: #a6e3a1; padding: 4px; font-weight: bold;")
        else:
            self._status_label.setText("WAITING")
            self._status_label.setStyleSheet("background: #313244; color: #f9e2af; padding: 4px; font-weight: bold;")

    def validate_inputs(self, allow_zero: bool = True) -> tuple[float, float, float] | None:
        parsed: dict[str, float] = {}
        for key in ("kp", "ki", "kd"):
            line_edit = self._inputs.get(key)
            if not line_edit or not line_edit.text().strip():
                self._last_error = f"Field {key.upper()} cannot be empty."
                self._feedback_label.setText(self._last_error)
                return None
            try:
                val = float(line_edit.text().strip())
                if val < 0.0 or val > 1000.0:
                    raise ValueError
                parsed[key] = val
            except ValueError:
                self._last_error = f"Invalid field {key.upper()}."
                self._feedback_label.setText(self._last_error)
                return None
        self._feedback_label.setText("")
        return (parsed["kp"], parsed["ki"], parsed["kd"])
