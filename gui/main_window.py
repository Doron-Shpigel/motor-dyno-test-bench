"""
Main Application Window.

Orchestrates the full control loop:
  - Owns the PLF (torque profile)
  - Owns the SerialWorker thread
  - Owns the DynoSession (data model)
  - Owns the CSVLogger
  - Owns a QTimer that ticks the control loop
  - Routes signals between ControlPanel ↔ PlotPanel

Control loop (per tick):
  1. Compute elapsed time.
  2. Query PLF → setpoint torque.
  3. Convert torque → DAC value → send SET command to Arduino.
  4. The SerialWorker's speed_received signal feeds the latest ADC value.
  5. Convert ADC → RPM.
  6. Append sample to DynoSession.
  7. Write sample to CSVLogger.
  8. Refresh plot and live readouts.
"""

import time

from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QWidget,
    QTabWidget,
)

from gui.pid_tuning_tab import PidTuningTab
from gui.calibration_dialog import CalibrationDialog, CalibrationSettings
from gui.control_panel import ControlPanel
from gui.csv_import_dialog import CSVImportDialog
from gui.plot_widget import PlotPanel
from gui.serial_config_dialog import SerialConfigDialog
from modules.csv_logger import CSVLogger
from modules.data_model import DynoSession, RunState, Sample
from modules.plf import PiecewiseLinearFunction
from modules.serial_comm import SerialWorker

PLOT_REFRESH_EVERY = 5   # update plots every N samples (reduces redraws)


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Dyno Control Software")
        self.resize(1200, 700)

        # -- State --
        self._plf        = PiecewiseLinearFunction()
        self._calibration = CalibrationSettings()
        self._session    = DynoSession()
        self._logger     = CSVLogger()
        self._worker: SerialWorker | None = None
        self._port: str  = ""
        self._connected  = False
        self._last_adc   = 0        # latest ADC value from serial thread
        self._last_rpm   = 0.0

        # Control-loop timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(6, 6, 6, 6)
        h_layout.setSpacing(6)

        # Left: control panel
        self._ctrl = ControlPanel()
        self._pid_tab = PidTuningTab()
        self._ctrl.sig_load_csv.connect(self._on_load_csv)
        self._ctrl.sig_connect.connect(self._on_connect)
        self._ctrl.sig_disconnect.connect(self._on_disconnect)
        self._ctrl.sig_start.connect(self._on_start)
        self._ctrl.sig_stop.connect(self._on_stop)
        self._ctrl.sig_reset.connect(self._on_reset)
        self._ctrl.sig_calibration.connect(self._on_calibration)
        
        # Create Left-Side Tabs
        self._left_tabs = QTabWidget()
        self._left_tabs.addTab(self._ctrl, "Control Panel")
        self._left_tabs.addTab(self._pid_tab, "PID Tuning")
        # Right: plots
        self._plots = PlotPanel()

        # UI: Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._left_tabs)
        splitter.addWidget(self._plots)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        h_layout.addWidget(splitter)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_msg = QLabel("Ready.")
        self._status_bar.addWidget(self._status_msg, 1)

        self._update_ui_state()

    # ------------------------------------------------------------------
    # Slots — user actions
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_load_csv(self) -> None:
        dlg = CSVImportDialog(self)
        if dlg.exec() and dlg.plf:
            self._plf = dlg.plf
            self._ctrl.set_profile_info(self._plf)
            self._status("Profile loaded: " + self._plf.summary())
        self._update_ui_state()

    @pyqtSlot()
    def _on_connect(self) -> None:
        dlg = SerialConfigDialog(self._port, self)
        if not dlg.exec():
            return
        self._port = dlg.selected_port
        self._ctrl.set_port_label(self._port)
        self._start_worker()

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        self._stop_worker()

    @pyqtSlot()
    def _on_start(self) -> None:
        if self._session.state == RunState.RUNNING:
            return

        # Open log file
        try:
            log_path = self._logger.open(self._calibration.output_dir)
            self._ctrl.set_log_path(log_path)
        except Exception as exc:
            self._show_error("Cannot open log file", str(exc))
            return

        # Tell Arduino to start streaming
        if self._worker:
            self._worker.send_command("START")

        self._session.start()
        self._timer.start(self._calibration.poll_interval_ms)
        self._status("Run started.")
        self._update_ui_state()

    @pyqtSlot()
    def _on_stop(self) -> None:
        self._timer.stop()
        if self._worker:
            self._worker.send_command("STOP")
        self._session.finish()
        if self._logger.is_open():
            self._logger.close()
        self._status(
            f"Run stopped. {self._session.sample_count()} samples logged → "
            f"{self._logger.path}"
        )
        self._update_ui_state()

    @pyqtSlot()
    def _on_reset(self) -> None:
        self._session.reset()
        self._plots.clear()
        self._ctrl.update_live(0.0, 0.0, 0.0, 0, 0)
        self._ctrl.set_log_path(None)
        self._status("Reset.")
        self._update_ui_state()

    @pyqtSlot()
    def _on_calibration(self) -> None:
        dlg = CalibrationDialog(self._calibration, self)
        dlg.exec()
        # timer interval updated on next start

    # ------------------------------------------------------------------
    # Control loop tick
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_tick(self) -> None:
        if self._session.state != RunState.RUNNING:
            return

        elapsed = self._session.elapsed_seconds()

        # Auto-stop when profile ends
        if elapsed > self._plf.duration:
            self._on_stop()
            return

        # Setpoint from PLF
        torque_nm = self._plf.torque_at(elapsed)

        # DAC value
        dac_raw = int(
            min(max(torque_nm / self._calibration.max_torque_nm, 0.0), 1.0) * 4095
        )
        if self._worker:
            self._worker.send_command(f"SET:{dac_raw}")

        # RPM from latest ADC
        rpm = self._last_adc * self._calibration.rpm_per_count

        sample = Sample(
            elapsed_s=elapsed,
            torque_nm=torque_nm,
            rpm=rpm,
            dac_raw=dac_raw,
            adc_raw=self._last_adc,
        )
        self._session.append_sample(sample)

        try:
            self._logger.write(sample)
        except Exception:
            pass  # don't crash the loop on a log error

        # Refresh live readouts every tick
        self._ctrl.update_live(elapsed, torque_nm, rpm, dac_raw, self._session.sample_count())

        # Refresh plots periodically
        if self._session.sample_count() % PLOT_REFRESH_EVERY == 0:
            self._plots.update_samples(self._session.get_snapshot())

    # ------------------------------------------------------------------
    # Serial worker management
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        if self._worker is not None:
            self._stop_worker()

        self._worker = SerialWorker(self._port, parent=self)
        self._worker.connected.connect(self._on_serial_connected)
        self._worker.disconnected.connect(self._on_serial_disconnected)
        self._worker.speed_received.connect(self._on_speed_received)
        self._worker.error_received.connect(self._on_serial_error)
        self._worker.ready.connect(lambda: self._status("Arduino ready."))
        self._worker.start()

    def _stop_worker(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(3000)
            self._worker = None

    # ------------------------------------------------------------------
    # Serial slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_serial_connected(self) -> None:
        self._connected = True
        self._ctrl.set_connection_status(True)
        self._status(f"Connected to {self._port}.")
        self._update_ui_state()

    @pyqtSlot()
    def _on_serial_disconnected(self) -> None:
        self._connected = False
        self._worker = None
        self._ctrl.set_connection_status(False)
        self._status("Disconnected.")
        if self._session.state == RunState.RUNNING:
            self._on_stop()
        self._update_ui_state()

    @pyqtSlot(int)
    def _on_speed_received(self, adc_val: int) -> None:
        self._last_adc = adc_val

    @pyqtSlot(str)
    def _on_serial_error(self, msg: str) -> None:
        self._status(f"Serial error: {msg}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_ui_state(self) -> None:
        can_start = (
            self._plf.is_loaded()
            and self._connected
            and self._session.state not in (RunState.RUNNING,)
        )
        self._ctrl.set_run_state(self._session.state, can_start)

    def _status(self, msg: str) -> None:
        self._status_msg.setText(msg)

    def _show_error(self, title: str, msg: str) -> None:
        QMessageBox.critical(self, title, msg)

    def closeEvent(self, event) -> None:
        if self._session.state == RunState.RUNNING:
            self._on_stop()
        self._stop_worker()
        event.accept()
