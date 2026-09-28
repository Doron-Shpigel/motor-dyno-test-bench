#!/usr/bin/env python3
"""
Dyno Control Software — entry point.

Run:
    python main.py

Requirements (install once):
    pip install -r requirements.txt
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main() -> None:
    # Enable HiDPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Dyno Control")
    app.setOrganizationName("DynoProject")

    # Dark palette via stylesheet
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        QGroupBox {
            border: 1px solid #45475a;
            border-radius: 6px;
            margin-top: 8px;
            padding-top: 6px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
            color: #89b4fa;
        }
        QPushButton {
            background-color: #313244;
            border: 1px solid #45475a;
            border-radius: 5px;
            padding: 5px 12px;
            color: #cdd6f4;
        }
        QPushButton:hover  { background-color: #45475a; }
        QPushButton:pressed { background-color: #585b70; }
        QPushButton:disabled { color: #585b70; }
        QLabel  { color: #cdd6f4; }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
            background-color: #313244;
            border: 1px solid #45475a;
            border-radius: 4px;
            padding: 3px 6px;
            color: #cdd6f4;
        }
        QTableWidget {
            background-color: #181825;
            alternate-background-color: #1e1e2e;
            gridline-color: #313244;
        }
        QHeaderView::section {
            background-color: #313244;
            color: #89b4fa;
            border: none;
            padding: 4px;
        }
        QTabWidget::pane {
            border: 1px solid #45475a;
            border-radius: 4px;
        }
        QTabBar::tab {
            background: #313244;
            color: #cdd6f4;
            padding: 5px 16px;
            border-radius: 4px 4px 0 0;
        }
        QTabBar::tab:selected { background: #45475a; color: #89b4fa; }
        QStatusBar { background-color: #181825; color: #a6adc8; font-size: 11px; }
        QSplitter::handle { background-color: #45475a; }
        QScrollBar:vertical {
            background: #1e1e2e; width: 10px; border-radius: 5px;
        }
        QScrollBar::handle:vertical {
            background: #45475a; border-radius: 5px; min-height: 20px;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
