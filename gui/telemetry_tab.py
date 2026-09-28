"""
Telemetry Tab

Displays raw serial output from the Arduino with options to clear or save.
"""

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class TelemetryTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Buttons row
        btn_layout = QHBoxLayout()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        self._save_btn = QPushButton("Save to File...")
        self._save_btn.clicked.connect(self._on_save)

        btn_layout.addWidget(self._clear_btn)
        btn_layout.addWidget(self._save_btn)
        btn_layout.addStretch(1)

        layout.addLayout(btn_layout)

        # Text output
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        # Use monospace font
        font = QFont("Courier", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._text_edit.setFont(font)
        self._text_edit.setStyleSheet("background-color: #11111b; color: #a6e3a1;")
        
        layout.addWidget(self._text_edit)

    @pyqtSlot(str)
    def append_line(self, line: str) -> None:
        """Appends a new verbatim line to the text box."""
        self._text_edit.append(line)

    @pyqtSlot()
    def _on_clear(self) -> None:
        """Clears the text area."""
        self._text_edit.clear()

    @pyqtSlot()
    def _on_save(self) -> None:
        """Opens a save dialog and writes the contents to a file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Telemetry",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._text_edit.toPlainText())
            except Exception as e:
                # Silently ignore write errors for now, or you could emit an error signal
                pass
