"""
PID & Stability Tuning Tab.

Provides two sections:
  1. Hardware PID Parameters — read/write Kp, Ki, Kd stored in Arduino EEPROM.
  2. Software Stability Monitor — configure tolerance and settling-time thresholds
     used by the PC-side steady-state detector.

No backend logic is implemented here; all action slots are stubs.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


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

class PidTuningTab(QWidget):
    """
    'PID & Stability Tuning' tab widget.

    Drop this into a QTabWidget:
        tabs.addTab(PidTuningTab(), "PID & Stability")
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(18)

        root.addWidget(self._build_hardware_pid_section())
        root.addWidget(_separator())
        root.addWidget(self._build_stability_monitor_section())
        root.addStretch(1)

    # ── Section 1: Hardware PID (Arduino EEPROM) ─────────────────────────

    def _build_hardware_pid_section(self) -> QGroupBox:
        group = QGroupBox()
        outer = QVBoxLayout(group)
        outer.setSpacing(12)

        outer.addWidget(_section_title("Arduino EEPROM PID Settings"))

        # ---- Current stored values (read-only) ----
        stored_label = QLabel("Current stored values (read from Arduino):")
        stored_label.setStyleSheet("font-size: 11px; color: #a6adc8;")
        outer.addWidget(stored_label)

        stored_grid = QGridLayout()
        stored_grid.setHorizontalSpacing(20)
        stored_grid.setVerticalSpacing(6)

        headers = ["Parameter", "Stored value"]
        for col, text in enumerate(headers):
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
        new_label = QLabel("New values to write:")
        new_label.setStyleSheet("font-size: 11px; color: #a6adc8;")
        outer.addWidget(new_label)

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

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._read_btn = QPushButton("Read from Arduino")
        self._read_btn.setToolTip("Query the Arduino for its current PID gains")
        self._read_btn.clicked.connect(self._on_read_from_arduino)

        self._save_btn = QPushButton("Save to Arduino")
        self._save_btn.setToolTip("Write the new values to Arduino EEPROM")
        self._save_btn.clicked.connect(self._on_save_to_arduino)

        for btn in (self._read_btn, self._save_btn):
            btn.setMinimumWidth(160)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

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
        params_grid.setHorizontalSpacing(20)
        params_grid.setVerticalSpacing(8)

        # Tolerance
        tol_label = QLabel("Tolerance (%):")
        tol_label.setToolTip(
            "RPM must stay within ±tolerance% of the setpoint\n"
            "for the full settling time before STABLE is declared."
        )
        self._tolerance_spin = QDoubleSpinBox()
        self._tolerance_spin.setRange(0.1, 50.0)
        self._tolerance_spin.setDecimals(1)
        self._tolerance_spin.setSingleStep(0.5)
        self._tolerance_spin.setValue(2.0)
        self._tolerance_spin.setSuffix("  %")
        self._tolerance_spin.setFixedWidth(110)

        params_grid.addWidget(tol_label, 0, 0)
        params_grid.addWidget(self._tolerance_spin, 0, 1)

        # Settling time
        settle_label = QLabel("Settling Time (Seconds):")
        settle_label.setToolTip(
            "How long the RPM must remain within tolerance\n"
            "before the system is considered stable."
        )
        self._settling_spin = QDoubleSpinBox()
        self._settling_spin.setRange(0.1, 60.0)
        self._settling_spin.setDecimals(1)
        self._settling_spin.setSingleStep(0.5)
        self._settling_spin.setValue(1.5)
        self._settling_spin.setSuffix("  s")
        self._settling_spin.setFixedWidth(110)

        params_grid.addWidget(settle_label, 1, 0)
        params_grid.addWidget(self._settling_spin, 1, 1)

        outer.addLayout(params_grid)

        # Status label
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(QLabel("Current Status:"))
        self._status_label = QLabel("WAITING")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setFixedWidth(120)
        self._status_label.setStyleSheet(
            "background: #313244; color: #f9e2af;"
            " border: 1px solid #45475a; border-radius: 4px;"
            " padding: 4px 8px; font-weight: bold;"
        )
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        outer.addLayout(status_row)

        # Update button
        btn_row = QHBoxLayout()
        self._update_btn = QPushButton("Update Software Parameters")
        self._update_btn.setToolTip("Apply the tolerance and settling-time values above")
        self._update_btn.setMinimumWidth(200)
        self._update_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._update_btn.clicked.connect(self._on_update_software_params)
        btn_row.addWidget(self._update_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        return group

    # ------------------------------------------------------------------
    # Public helpers — call these from outside to reflect backend state
    # ------------------------------------------------------------------

    def set_stored_values(self, kp: float, ki: float, kd: float) -> None:
        """Populate the read-only 'stored values' fields."""
        self._stored["kp"].setText(f"{kp:.4f}")
        self._stored["ki"].setText(f"{ki:.4f}")
        self._stored["kd"].setText(f"{kd:.4f}")

    def set_stability_status(self, stable: bool) -> None:
        """Update the status badge to STABLE (green) or WAITING (amber)."""
        if stable:
            self._status_label.setText("STABLE")
            self._status_label.setStyleSheet(
                "background: #1e4a2a; color: #a6e3a1;"
                " border: 1px solid #45475a; border-radius: 4px;"
                " padding: 4px 8px; font-weight: bold;"
            )
        else:
            self._status_label.setText("WAITING")
            self._status_label.setStyleSheet(
                "background: #313244; color: #f9e2af;"
                " border: 1px solid #45475a; border-radius: 4px;"
                " padding: 4px 8px; font-weight: bold;"
            )

    # ------------------------------------------------------------------
    # Action stubs — replace bodies with real logic when ready
    # ------------------------------------------------------------------

    def _on_read_from_arduino(self) -> None:
        """Request current PID gains from Arduino EEPROM."""
        print("[PidTuningTab] Read from Arduino — not yet implemented")

    def _on_save_to_arduino(self) -> None:
        """Validate inputs and write new PID gains to Arduino EEPROM."""
        print("[PidTuningTab] Save to Arduino — not yet implemented")

    def _on_update_software_params(self) -> None:
        """Push tolerance / settling-time values to the PC stability monitor."""
        print(
            f"[PidTuningTab] Update software params — "
            f"tolerance={self._tolerance_spin.value():.1f}%, "
            f"settling={self._settling_spin.value():.1f}s — not yet implemented"
        )
