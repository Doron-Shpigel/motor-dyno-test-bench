"""
Main Application Window.

Orchestrates the full control loop:
  - Owns the PLF (torque profile)
  - Owns the SerialWorker thread
  - Owns the DynoSession (data model)
  - Owns the CSVLogger
  - Owns a QTimer that ticks the control loop
  - Routes signals between ControlPanel ↔ PlotPanel
"""

import datetime
import time

from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QWidget,
    QTabWidget,
)

from gui.settings_tab import SettingsTab, CalibrationSettings
from gui.control_panel import ControlPanel
from gui.csv_import_dialog import CSVImportDialog
from gui.plot_widget import PlotPanel
from gui.serial_config_dialog import SerialConfigDialog
from gui.telemetry_tab import TelemetryTab
from modules.csv_logger import CSVLogger
from modules.data_model import DynoSession, RunState, RunMode, Sample
from modules.plf import PiecewiseLinearFunction
from modules.serial_comm import SerialWorker
from modules.stability_monitor import StabilityMonitor

PLOT_REFRESH_EVERY = 5   # update plots every N samples (reduces redraws)


class MainWindow(QMainWindow):

    def __init__(self, debug: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Dyno Control Software")
        self.resize(1200, 700)
        self._debug = debug

        # -- State --
        self._plf        = PiecewiseLinearFunction()
        self._calibration = CalibrationSettings()
        # Add a missing property to calibration for torque mapping
        self._calibration.torque_per_count = 5.0 / (1023.0 - 512.0)
        
        self._session    = DynoSession()
        self._logger     = CSVLogger()
        self._stability_monitor = StabilityMonitor()
        self._worker: SerialWorker | None = None
        self._port: str  = ""
        self._connected  = False
        
        # Run state
        self._current_step_idx: int = 0
        self._current_target_torque: float = 0.0
        self._pid_active: bool = False
        self._step_start_time: float = 0.0
        self._step_timeout_s: float  = 30.0
        self._run_timestamp: str = ""
        self._log_saved: bool = True
        
        # Calibration state
        self._is_calibrating = False
        self._max_calib_reading = 0.0

        # Telemetry
        self._last_torque_raw: float = 0.0
        self._last_torque_nm: float = 0.0
        self._last_speed: float  = 0.0
        self._last_dac: int      = 0
        self._last_adc: int      = 0        # latest ADC value from serial thread
        self._last_rpm: float    = 0.0

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
        self._settings_tab = SettingsTab(self._calibration)
        
        self._ctrl.sig_load_csv.connect(self._on_load_csv)
        self._ctrl.sig_connect.connect(self._on_connect)
        self._ctrl.sig_disconnect.connect(self._on_disconnect)
        
        self._ctrl.sig_start_profile.connect(self._on_start_profile)
        self._ctrl.sig_stop_profile.connect(self._on_stop)
        
        self._ctrl.sig_start_manual.connect(self._on_start_manual)
        self._ctrl.sig_stop_manual.connect(self._on_stop)
        self._ctrl.sig_manual_torque_changed.connect(self._on_manual_torque_changed)
        
        self._ctrl.sig_choose_log_dir.connect(self._on_choose_log_dir)
        self._ctrl.sig_save_log.connect(self._on_save_log)
        
        # Hardware Relays
        self._ctrl.sig_relay_brake.connect(lambda state: self._send_command(f"<RELAY:BRAKE,{1 if state else 0}>"))
        self._ctrl.sig_relay_sensor.connect(lambda state: self._send_command(f"<RELAY:SENSOR,{1 if state else 0}>"))
        self._ctrl.sig_relay_aux.connect(lambda state: self._send_command(f"<RELAY:AUX,{1 if state else 0}>"))
        
        # Create Left-Side Tabs
        self._left_tabs = QTabWidget()
        self._left_tabs.addTab(self._ctrl, "Control Panel")
        self._left_tabs.addTab(self._settings_tab, "Settings")
        self._telemetry_tab = TelemetryTab()
        self._left_tabs.addTab(self._telemetry_tab, "Telemetry")

        # Wire Settings tab signals
        self._settings_tab.sig_send_command.connect(self._send_command)
        self._settings_tab.sig_update_stability_params.connect(self._on_update_stability_params)
        self._settings_tab.sig_update_calibration.connect(self._on_update_calibration)
        self._settings_tab.sig_start_torque_calibration.connect(self._on_start_calibration)
        self._settings_tab.sig_finish_torque_calibration.connect(self._on_finish_calibration)
        
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
    
    def _send_command(self, cmd: str) -> None:
        if self._worker and self._connected:
            self._worker.send_command(cmd)

    @pyqtSlot()
    def _on_load_csv(self) -> None:
        dlg = CSVImportDialog(self)
        if dlg.exec() and dlg.plf:
            self._plf = dlg.plf
            self._ctrl.set_profile_info(self._plf)
            self._status("Profile loaded: " + self._plf.summary())
        self._update_ui_state()

    @pyqtSlot()
    def _on_choose_log_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory", str(self._calibration.output_dir))
        if path:
            self._calibration.output_dir = Path(path)
            self._status(f"Log directory set to {path}")

    @pyqtSlot()
    def _on_save_log(self) -> None:
        if self._log_saved:
            return
        final_path = self._logger.save_to(self._calibration.output_dir, self._run_timestamp)
        if final_path:
            self._ctrl.set_log_path(final_path)
            self._log_saved = True
            self._status(f"Log saved to {final_path}")
            self._ctrl._save_log_btn.setEnabled(False)
            
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

    def _command_torque_setpoint(self, torque: float) -> None:
        """Applies Hybrid Control Logic for a new torque setpoint."""
        if self._last_rpm > 1.0:
            self._send_command(f"<SET_TORQUE:{torque:.2f}>")
            self._pid_active = True
        else:
            # Pre-calculate open-loop DAC based on max torque (linear mapping)
            dac = int((torque / self._calibration.max_torque_nm) * 4095)
            dac = max(0, min(4095, dac))
            self._send_command(f"<SET_DAC:{dac}>")
            self._pid_active = False

    @pyqtSlot(float)
    def _on_manual_torque_changed(self, torque: float) -> None:
        if self._session.state == RunState.RUNNING and self._session.run_mode == RunMode.MANUAL:
            self._current_target_torque = torque
            self._stability_monitor.reset()
            self._settings_tab.set_stability_status(False)
            self._command_torque_setpoint(self._current_target_torque)

    @pyqtSlot()
    def _on_start_profile(self) -> None:
        if self._session.state == RunState.RUNNING:
            return
            
        self._on_reset()

        # Check PLF
        if not self._plf.is_loaded() or len(self._plf.torques) == 0:
            self._show_error("Cannot Start", "No valid profile loaded.")
            return

        self._start_run_common(RunMode.PROFILE)
        
        # Initialize closed-loop stepping state
        self._current_step_idx = 0
        self._current_target_torque = float(self._plf.torques[0])
        self._step_start_time = time.perf_counter()
        
        if self._worker:
            self._command_torque_setpoint(self._current_target_torque)

        self._status(
            f"Profile Run started. Setpoint 1/{len(self._plf.torques)}: "
            f"{self._current_target_torque:.2f} N·m"
        )
        
    @pyqtSlot()
    def _on_start_manual(self) -> None:
        if self._session.state == RunState.RUNNING:
            return
            
        self._on_reset()

        self._start_run_common(RunMode.MANUAL)
        self._current_target_torque = self._ctrl.get_manual_torque()
        
        if self._worker:
            self._command_torque_setpoint(self._current_target_torque)

        self._status(f"Manual Run started. Setpoint: {self._current_target_torque:.2f} N·m")

    def _start_run_common(self, mode: RunMode) -> None:
        # Open temp log file
        try:
            self._logger.open_temp()
            self._run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_saved = False
            self._ctrl.set_log_path(self._logger.path)
        except Exception as exc:
            self._show_error("Cannot open log file", str(exc))
            return

        self._stability_monitor.reset()
        self._settings_tab.set_stability_status(False)

        if self._worker:
            self._send_command("START")

        self._session.start(mode)
        self._timer.start(self._calibration.poll_interval_ms)
        self._update_ui_state()

    @pyqtSlot()
    def _on_stop(self) -> None:
        self._timer.stop()
        if self._worker:
            self._send_command("STOP")
        self._session.finish()
        if self._logger.is_open():
            self._logger.close()
            
        # Reset hardware relays to OFF on stop
        self._ctrl._brake_relay_btn.setChecked(False)
        self._ctrl._sensor_relay_btn.setChecked(False)
        self._ctrl._aux_relay_btn.setChecked(False)
        
        self._stability_monitor.reset()
        self._settings_tab.set_stability_status(False)
        self._status(
            f"Run stopped. {self._session.sample_count()} samples logged. Ready to save."
        )
        self._update_ui_state()

    @pyqtSlot()
    def _on_reset(self) -> None:
        if self._session.state == RunState.RUNNING:
            self._on_stop()
            
        if not self._log_saved:
            self._on_save_log()
            
        self._session.reset()
        self._plots.clear()
        self._ctrl.reset_manual_torque()
        self._ctrl.update_run_stats(0.0, 0)
        self._ctrl.set_log_path(None)
        self._current_step_idx = 0
        self._current_target_torque = 0.0
        self._last_torque_raw = 0.0
        self._last_torque_nm = 0.0
        self._last_speed = 0.0
        self._last_dac = 0
        self._last_adc = 0
        self._last_rpm = 0.0
        self._stability_monitor.reset()
        self._settings_tab.set_stability_status(False)
        self._status("Reset.")
        self._update_ui_state()

    # ------------------------------------------------------------------
    # Control loop tick
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_tick(self) -> None:
        if self._session.state != RunState.RUNNING:
            return

        elapsed = self._session.elapsed_seconds()
        now = time.perf_counter()

        # Hybrid Logic check: if motor starts spinning, hand over to PID
        if not self._pid_active and self._last_rpm > 1.0:
            self._send_command(f"<SET_TORQUE:{self._current_target_torque:.2f}>")
            self._pid_active = True

        # 1. Evaluate steady-state stability
        is_stable = self._stability_monitor.is_stable(self._current_target_torque)
        self._settings_tab.set_stability_status(is_stable)

        # 2. If Profile mode, gate profile stepping on stability (or safety timeout fallback)
        if self._session.run_mode == RunMode.PROFILE:
            if is_stable:
                next_idx = self._current_step_idx + 1
                if next_idx >= len(self._plf.torques):
                    self._on_stop()
                    self._status("Profile completed successfully.")
                    return
                else:
                    self._current_step_idx = next_idx
                    self._current_target_torque = float(self._plf.torques[next_idx])
                    self._step_start_time = now
                    self._stability_monitor.reset()
                    self._settings_tab.set_stability_status(False)
                    self._command_torque_setpoint(self._current_target_torque)
                    
                    self._status(
                        f"Stepping to setpoint {next_idx + 1}/{len(self._plf.torques)}: "
                        f"{self._current_target_torque:.2f} N·m"
                    )
            else:
                # Check safety step timeout
                if (now - self._step_start_time) > self._step_timeout_s:
                    warning_prefix = (
                        f"Warning: Setpoint {self._current_step_idx + 1} timed out waiting for stability."
                    )
                    next_idx = self._current_step_idx + 1
                    if next_idx >= len(self._plf.torques):
                        self._on_stop()
                        self._status(f"{warning_prefix} Profile finished on timeout.")
                        return
                    else:
                        self._current_step_idx = next_idx
                        self._current_target_torque = float(self._plf.torques[next_idx])
                        self._step_start_time = now
                        self._stability_monitor.reset()
                        self._settings_tab.set_stability_status(False)
                        self._command_torque_setpoint(self._current_target_torque)

                        self._status(
                            f"{warning_prefix} Stepping to setpoint {next_idx + 1}/{len(self._plf.torques)}: "
                            f"{self._current_target_torque:.2f} N·m"
                        )

        # 3. Append authentic sample using genuine physical telemetry
        sample = Sample(
            elapsed_s=elapsed,
            torque_nm=self._last_torque_nm,
            rpm=self._last_rpm,
            dac_raw=self._last_dac,
            adc_raw=self._last_adc,
            target_torque_nm=self._current_target_torque,
        )
        self._session.append_sample(sample)

        try:
            self._logger.write(sample)
        except Exception:
            pass  # don't crash the loop on a log error

        # 4. Refresh live run stats every tick
        self._ctrl.update_run_stats(
            elapsed,
            self._session.sample_count(),
        )

        # 5. Refresh plots periodically
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
        self._worker.data_received.connect(self._on_data_received)
        self._worker.speed_received.connect(self._on_speed_received)
        if hasattr(self._worker, "ack_received"):
            self._worker.ack_received.connect(self._on_serial_ack)
        self._worker.error_received.connect(self._on_serial_error)
        self._worker.ready.connect(self._on_arduino_ready)
        self._worker.pid_received.connect(self._settings_tab.set_stored_values)
        self._worker.pid_received.connect(self._on_pid_received)
        self._worker.raw_line_received.connect(self._telemetry_tab.append_line)
        self._worker.start()

    def _stop_worker(self) -> None:
        self._connected = False
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.stop()
            worker.wait(3000)

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

    @pyqtSlot(float, float, int)
    def _on_data_received(self, torque_adc: float, speed: float, dac: int) -> None:
        self._last_torque_raw = torque_adc
        self._last_torque_nm = (torque_adc - 512.0) * self._calibration.torque_per_count
        self._last_speed = speed
        self._last_dac = dac
        self._last_rpm = speed * self._calibration.rpm_per_count
        self._last_adc = int(speed)
        
        # Live update of sensor readings in the GUI
        self._ctrl.update_sensor_readings(self._last_torque_nm, self._last_rpm, self._last_dac)
        
        # Max Torque Calibration Logic
        if self._is_calibrating:
            self._max_calib_reading = max(self._max_calib_reading, self._last_torque_raw)
            if self._last_rpm > 1.0:
                self._settings_tab._on_finish_calibration() # Auto finish

        # Ingest into stability monitor
        self._stability_monitor.add_reading(self._last_torque_nm, time.perf_counter())

        # Live update stability badge
        if self._session.state == RunState.RUNNING:
            stable = self._stability_monitor.is_stable(self._current_target_torque)
            self._settings_tab.set_stability_status(stable)

    @pyqtSlot(int)
    def _on_speed_received(self, adc_val: int) -> None:
        self._last_adc = adc_val
        self._last_rpm = adc_val * self._calibration.rpm_per_count

    @pyqtSlot(str)
    def _on_serial_ack(self, ack_text: str) -> None:
        cleaned = ack_text[4:].strip() if ack_text.startswith("ACK:") else ack_text.strip()
        if cleaned.startswith("SET_PID"):
            self._status("PID gains acknowledged and saved to Arduino EEPROM.")
        elif cleaned.startswith("SET_TORQUE"):
            self._status(f"Arduino acknowledged target torque setpoint: {cleaned}")
        else:
            self._status(f"Arduino ACK: {ack_text}")

    @pyqtSlot(str)
    def _on_serial_error(self, msg: str) -> None:
        self._status(f"Serial error: {msg}")

    # ------------------------------------------------------------------
    # PID & Settings slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_arduino_ready(self) -> None:
        self._status("Arduino ready. Querying PID parameters...")
        if self._worker:
            self._worker.send_get_pid()

    @pyqtSlot(float, float, float)
    def _on_pid_received(self, kp: float, ki: float, kd: float) -> None:
        self._status(f"Arduino PID updated: Kp={kp:.4f}, Ki={ki:.4f}, Kd={kd:.4f}")

    @pyqtSlot(float, float)
    def _on_update_stability_params(self, tolerance_pct: float, settling_time_s: float) -> None:
        if hasattr(self, "_stability_monitor") and self._stability_monitor is not None:
            self._stability_monitor.set_parameters(tolerance_pct, settling_time_s)
        self._status(f"Stability parameters updated: ±{tolerance_pct:.1f}%, {settling_time_s:.1f}s")
        
    @pyqtSlot()
    def _on_update_calibration(self) -> None:
        self._timer.setInterval(self._calibration.poll_interval_ms)
        self._status("App settings updated.")
        
    @pyqtSlot()
    def _on_start_calibration(self) -> None:
        self._is_calibrating = True
        self._max_calib_reading = 0.0
        self._send_command("<RELAY:SENSOR,1>")
        self._send_command("<SET_DAC:4095>")
        
    @pyqtSlot()
    def _on_finish_calibration(self) -> None:
        self._is_calibrating = False
        self._send_command("<SET_DAC:0>")
        self._send_command("<RELAY:SENSOR,0>")
        
        # Calculate new mapping factor (max torque is exactly 5 N·m)
        if self._max_calib_reading > 512.0:
            self._calibration.torque_per_count = 5.0 / (self._max_calib_reading - 512.0)
            self._calibration.max_torque_nm = 5.0 # For open loop mapping reference
            self._status(f"Calibration successful: Peak ADC {self._max_calib_reading:.0f} mapped to 5 N·m.")
        else:
            self._status("Calibration failed: insufficient force applied.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_ui_state(self) -> None:
        can_start = (
            self._plf.is_loaded()
            and len(self._plf.torques) > 0
        )
        self._ctrl.set_run_state(self._session.state, self._session.run_mode, can_start, self._connected)

    def _status(self, msg: str) -> None:
        self._status_msg.setText(msg)
        if getattr(self, "_debug", False):
            print(f"[Dyno] {msg}")

    def _show_error(self, title: str, msg: str) -> None:
        QMessageBox.critical(self, title, msg)

    def closeEvent(self, event) -> None:
        if self._session.state == RunState.RUNNING:
            self._on_stop()
        self._stop_worker()
        event.accept()

