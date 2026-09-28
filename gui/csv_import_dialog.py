"""
CSV Import Dialog.

Lets the user browse for a torque-profile CSV, validates it,
and shows a preview table.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules.plf import PiecewiseLinearFunction, PLFError


class CSVImportDialog(QDialog):
    """
    Modal dialog for loading and validating a torque-profile CSV.

    After exec():
        dialog.plf       — loaded PiecewiseLinearFunction (or None on cancel)
        dialog.csv_path  — Path to the chosen file
    """

    MAX_PREVIEW_ROWS = 200

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Torque Profile CSV")
        self.setMinimumSize(520, 440)
        self.plf: PiecewiseLinearFunction | None = None
        self.csv_path: Path | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- File picker ----
        file_group = QGroupBox("CSV File")
        f_layout = QHBoxLayout(file_group)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("No file selected…")
        self._path_edit.setReadOnly(True)
        f_layout.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        f_layout.addWidget(browse_btn)
        layout.addWidget(file_group)

        # ---- Status / summary ----
        self._status_label = QLabel(
            "Required columns: time_s, torque_nm (header row, comma-separated)"
        )
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # ---- Preview table ----
        preview_group = QGroupBox("Preview")
        p_layout = QVBoxLayout(preview_group)
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["time_s", "torque_nm"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        p_layout.addWidget(self._table)
        layout.addWidget(preview_group, stretch=1)

        # ---- Buttons ----
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Torque Profile CSV",
            str(Path.home()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return
        self._load_file(Path(filepath))

    def _load_file(self, path: Path) -> None:
        plf = PiecewiseLinearFunction()
        try:
            plf.load_csv(path)
        except (PLFError, FileNotFoundError) as exc:
            self._status_label.setText(f"Error: {exc}")
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            self._clear_table()
            return

        self.plf = plf
        self.csv_path = path
        self._path_edit.setText(str(path))
        self._status_label.setText(f"OK — {plf.summary()}")
        self._populate_table(plf)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _populate_table(self, plf: PiecewiseLinearFunction) -> None:
        n = min(len(plf.times), self.MAX_PREVIEW_ROWS)
        self._table.setRowCount(n)
        for i in range(n):
            self._table.setItem(i, 0, QTableWidgetItem(f"{plf.times[i]:.4f}"))
            self._table.setItem(i, 1, QTableWidgetItem(f"{plf.torques[i]:.4f}"))

    def _clear_table(self) -> None:
        self._table.setRowCount(0)
