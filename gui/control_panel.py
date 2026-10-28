"""
Control Panel Widget.

Left-hand panel that manages the test lifecycle:
  - Load torque-profile CSV
  - Start / Stop / Reset Profile Mode runs
  - Manual Control mode (adjust torque manually)
  - Connect / disconnect Arduino
  - Hardware Relays
  - Live status readouts
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from modules.data_model import RunState, RunMode
from modules.plf import PiecewiseLinearFunction


# ── tiny helper ──────────────────────────────────────────────────────────────
def _separator() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _value_label(text: str = "—") -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(13)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


# ── Control Panel ─────────────────────────────────────────────────────────────
class ControlPanel(QWidget):

    sig_load_csv    = pyqtSignal()
    sig_connect     = pyqtSignal()
    sig_disconnect  = pyqtSignal()
    
    sig_start_profile = pyqtSignal()
    sig_stop_profile  = pyqtSignal()

    sig_start_manual = pyqtSignal()
    sig_stop_manual  = pyqtSignal()
    sig_manual_torque_changed = pyqtSignal(float)
    sig_manual_mode_changed = pyqtSignal(str)
    
    sig_choose_log_dir = pyqtSignal()
    sig_save_log       = pyqtSignal()
    
    sig_relay_brake  = pyqtSignal(bool)
    sig_relay_sensor = pyqtSignal(bool)
    sig_relay_aux    = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(280)
        self._manual_torque = 0.0
        self._max_torque_nm = 5.0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        root.setSpacing(10)

        # ── Profile ──────────────────────────────────────────────────
        prof_group = QGroupBox("Torque Profile")
        pg_layout = QVBoxLayout(prof_group)

        self._load_btn = QPushButton("Load CSV…")
        self._load_btn.clicked.connect(self.sig_load_csv)
        pg_layout.addWidget(self._load_btn)

        self._profile_info = QLabel("No profile loaded.")
        self._profile_info.setWordWrap(True)
        self._profile_info.setStyleSheet("font-size: 11px; color: gray;")
        pg_layout.addWidget(self._profile_info)
        
        prof_btn_row = QHBoxLayout()
        self._prof_start_btn = QPushButton("▶  Start")
        self._prof_start_btn.setEnabled(False)
        self._prof_start_btn.clicked.connect(self.sig_start_profile)
        self._prof_stop_btn = QPushButton("■  Stop")
        self._prof_stop_btn.setEnabled(False)
        self._prof_stop_btn.clicked.connect(self.sig_stop_profile)
        prof_btn_row.addWidget(self._prof_start_btn)
        prof_btn_row.addWidget(self._prof_stop_btn)
        pg_layout.addLayout(prof_btn_row)
        
        root.addWidget(prof_group)
        
        # ── Manual Control ───────────────────────────────────────────
        man_group = QGroupBox("Manual Control")
        mg_layout = QVBoxLayout(man_group)
        
        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("font-size: 11px;")
        self._man_mode_combo = QComboBox()
        self._man_mode_combo.addItem("Open Loop (DAC)", "open_loop")
        self._man_mode_combo.addItem("Hybrid (Auto PID)", "hybrid")
        self._man_mode_combo.addItem("Closed Loop (PID)", "closed_loop")
        self._man_mode_combo.currentIndexChanged.connect(self._on_manual_mode_changed)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._man_mode_combo, stretch=1)
        mg_layout.addLayout(mode_row)

        man_ctrl_row = QHBoxLayout()
        self._man_minus_btn = QPushButton("➖")
        self._man_minus_btn.setFixedWidth(40)
        self._man_minus_btn.clicked.connect(self._on_manual_minus)
        
        self._man_torque_val = QLabel("0.0 N·m")
        self._man_torque_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self._man_torque_val.setFont(font)
        
        self._man_plus_btn = QPushButton("➕")
        self._man_plus_btn.setFixedWidth(40)
        self._man_plus_btn.clicked.connect(self._on_manual_plus)
        
        man_ctrl_row.addWidget(self._man_minus_btn)
        man_ctrl_row.addWidget(self._man_torque_val, stretch=1)
        man_ctrl_row.addWidget(self._man_plus_btn)
        mg_layout.addLayout(man_ctrl_row)

        self._man_dac_val = QLabel("DAC: 0 / 4095")
        self._man_dac_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._man_dac_val.setStyleSheet("font-size: 11px; color: #89b4fa;")
        mg_layout.addWidget(self._man_dac_val)
        
        man_btn_row = QHBoxLayout()
        self._man_start_btn = QPushButton("▶  Start")
        self._man_start_btn.setEnabled(False)
        self._man_start_btn.clicked.connect(self.sig_start_manual)
        self._man_stop_btn = QPushButton("■  Stop")
        self._man_stop_btn.setEnabled(False)
        self._man_stop_btn.clicked.connect(self.sig_stop_manual)
        man_btn_row.addWidget(self._man_start_btn)
        man_btn_row.addWidget(self._man_stop_btn)
        mg_layout.addLayout(man_btn_row)

        root.addWidget(man_group)

        # ── Connection ───────────────────────────────────────────────
        conn_group = QGroupBox("Arduino Connection")
        cg_layout = QVBoxLayout(conn_group)

        self._port_label = QLabel("Port: —")
        self._port_label.setStyleSheet("font-size: 11px;")
        cg_layout.addWidget(self._port_label)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect…")
        self._connect_btn.clicked.connect(self.sig_connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self.sig_disconnect)
        self._disconnect_btn.setEnabled(False)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        cg_layout.addLayout(btn_row)

        self._conn_status = QLabel("Disconnected")
        self._conn_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._conn_status.setStyleSheet(
            "background: #3b3b4f; border-radius: 4px; padding: 3px; font-size: 11px;"
        )
        cg_layout.addWidget(self._conn_status)
        root.addWidget(conn_group)

        # ── Hardware Control (Relays) ────────────────────────────────
        hw_group = QGroupBox("Hardware Relays")
        hw_layout = QVBoxLayout(hw_group)
        
        relay_style = (
            "QPushButton:checked { background-color: #2e663a; color: white; border: 1px solid #1e4a2a; }"
            "QPushButton:!checked { background-color: #a63232; color: white; border: 1px solid #732323; }"
        )
        
        self._brake_relay_btn = QPushButton("Brake Power")
        self._brake_relay_btn.setCheckable(True)
        self._brake_relay_btn.setStyleSheet(relay_style)
        self._brake_relay_btn.toggled.connect(self.sig_relay_brake)
        hw_layout.addWidget(self._brake_relay_btn)
        
        self._sensor_relay_btn = QPushButton("Torque and speed Sensor")
        self._sensor_relay_btn.setCheckable(True)
        self._sensor_relay_btn.setStyleSheet(relay_style)
        self._sensor_relay_btn.toggled.connect(self.sig_relay_sensor)
        hw_layout.addWidget(self._sensor_relay_btn)
        
        self._aux_relay_btn = QPushButton("Auxiliary")
        self._aux_relay_btn.setCheckable(True)
        self._aux_relay_btn.setStyleSheet(relay_style)
        self._aux_relay_btn.toggled.connect(self.sig_relay_aux)
        hw_layout.addWidget(self._aux_relay_btn)
        
        root.addWidget(hw_group)
        root.addWidget(_separator())

        # ── Live readouts ────────────────────────────────────────────
        live_group = QGroupBox("Live Readings")
        lg = QVBoxLayout(live_group)

        def _row(label: str) -> QLabel:
            row_w = QWidget()
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel(label))
            val = _value_label()
            rl.addWidget(val)
            lg.addWidget(row_w)
            return val

        self._time_val    = _row("Elapsed:")
        self._torque_val  = _row("Torque:")
        self._rpm_val     = _row("RPM:")
        self._dac_val     = _row("DAC:")
        self._samples_val = _row("Samples:")
        root.addWidget(live_group)

        root.addWidget(_separator())

        # ── Log file ─────────────────────────────────────────────────
        log_group = QGroupBox("Log File")
        log_layout = QVBoxLayout(log_group)
        
        self._log_label = QLabel("—")
        self._log_label.setWordWrap(True)
        self._log_label.setStyleSheet("font-size: 10px; color: gray;")
        log_layout.addWidget(self._log_label)
        
        log_btn_row = QHBoxLayout()
        self._choose_log_dir_btn = QPushButton("Choose Dir…")
        self._choose_log_dir_btn.clicked.connect(self.sig_choose_log_dir)
        self._save_log_btn = QPushButton("Save Log")
        self._save_log_btn.setEnabled(False)
        self._save_log_btn.clicked.connect(self.sig_save_log)
        
        log_btn_row.addWidget(self._choose_log_dir_btn)
        log_btn_row.addWidget(self._save_log_btn)
        log_layout.addLayout(log_btn_row)
        
        root.addWidget(log_group)

        root.addStretch(1)

    # ------------------------------------------------------------------
    # Update helpers (called from MainWindow)
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_manual_mode_changed(self, index: int) -> None:
        mode = self.get_manual_control_mode()
        self.sig_manual_mode_changed.emit(mode)

    def get_manual_control_mode(self) -> str:
        return self._man_mode_combo.currentData() or "open_loop"

    def set_manual_control_mode(self, mode: str) -> None:
        idx = self._man_mode_combo.findData(mode)
        if idx >= 0:
            self._man_mode_combo.setCurrentIndex(idx)

    def set_max_torque(self, max_torque: float) -> None:
        self._max_torque_nm = max(0.1, float(max_torque))
        self._update_manual_display()

    def get_manual_dac(self) -> int:
        dac = int(round((self._manual_torque / self._max_torque_nm) * 4095))
        return max(0, min(4095, dac))

    def _update_manual_display(self) -> None:
        self._man_torque_val.setText(f"{self._manual_torque:.1f} N·m")
        dac = self.get_manual_dac()
        self._man_dac_val.setText(f"DAC: {dac} / 4095")
    
    @pyqtSlot()
    def _on_manual_minus(self) -> None:
        self._manual_torque = max(0.0, self._manual_torque - 0.1)
        self._update_manual_display()
        self.sig_manual_torque_changed.emit(self._manual_torque)

    @pyqtSlot()
    def _on_manual_plus(self) -> None:
        self._manual_torque += 0.1
        self._update_manual_display()
        self.sig_manual_torque_changed.emit(self._manual_torque)
        
    def get_manual_torque(self) -> float:
        return self._manual_torque
        
    def reset_manual_torque(self) -> None:
        self._manual_torque = 0.0
        self._update_manual_display()

    def set_profile_info(self, plf: PiecewiseLinearFunction | None) -> None:
        if plf and plf.is_loaded():
            self._profile_info.setText(plf.summary())
            self._profile_info.setStyleSheet("font-size: 11px; color: #a6e3a1;")
        else:
            self._profile_info.setText("No profile loaded.")
            self._profile_info.setStyleSheet("font-size: 11px; color: gray;")

    def set_port_label(self, port: str) -> None:
        self._port_label.setText(f"Port: {port or '—'}")

    def set_connection_status(self, connected: bool) -> None:
        if connected:
            self._conn_status.setText("Connected")
            self._conn_status.setStyleSheet(
                "background: #1e4a2a; color: #a6e3a1; border-radius: 4px; padding: 3px; font-size: 11px;"
            )
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
        else:
            self._conn_status.setText("Disconnected")
            self._conn_status.setStyleSheet(
                "background: #3b3b4f; border-radius: 4px; padding: 3px; font-size: 11px;"
            )
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)

    def set_run_state(self, state: RunState, mode: RunMode, can_start_profile: bool, connected: bool) -> None:
        running = state == RunState.RUNNING
        idle    = state in (RunState.IDLE, RunState.FINISHED, RunState.ERROR)
        finished = state == RunState.FINISHED
        
        # Mutual Exclusion Logic
        if mode == RunMode.PROFILE and not idle:
            # Profile running or finished: disable manual controls completely
            self._prof_start_btn.setEnabled(False)
            self._prof_stop_btn.setEnabled(running)
            
            self._man_start_btn.setEnabled(False)
            self._man_stop_btn.setEnabled(False)
            self._man_plus_btn.setEnabled(False)
            self._man_minus_btn.setEnabled(False)
            self._man_mode_combo.setEnabled(False)
            self._load_btn.setEnabled(False)
            
        elif mode == RunMode.MANUAL and not idle:
            # Manual running or finished: disable profile controls completely
            self._prof_start_btn.setEnabled(False)
            self._prof_stop_btn.setEnabled(False)
            self._load_btn.setEnabled(False)
            
            self._man_start_btn.setEnabled(False)
            self._man_stop_btn.setEnabled(running)
            self._man_plus_btn.setEnabled(True)
            self._man_minus_btn.setEnabled(True)
            self._man_mode_combo.setEnabled(False)
            
        else: # NONE / IDLE
            # Neither is running. Enable controls based on connection / loaded state
            self._load_btn.setEnabled(True)
            self._prof_start_btn.setEnabled(can_start_profile and connected)
            self._prof_stop_btn.setEnabled(False)
            
            self._man_start_btn.setEnabled(connected)
            self._man_stop_btn.setEnabled(False)
            self._man_plus_btn.setEnabled(True)
            self._man_minus_btn.setEnabled(True)
            self._man_mode_combo.setEnabled(True)
            
        # Log buttons
        self._choose_log_dir_btn.setEnabled(not running)
        self._save_log_btn.setEnabled(finished)


    def is_sensor_relay_on(self) -> bool:
        return self._sensor_relay_btn.isChecked()

    def update_run_stats(self, elapsed_s: float, samples: int) -> None:
        self._time_val.setText(f"{elapsed_s:7.2f} s")
        self._samples_val.setText(f"{samples}")

    def update_sensor_readings(
        self,
        torque_nm: float,
        rpm: float,
        dac_raw: int,
    ) -> None:
        if self.is_sensor_relay_on():
            self._torque_val.setText(f"{torque_nm:7.3f} N·m")
            self._rpm_val.setText(f"{rpm:7.1f}")
        else:
            self._torque_val.setText("—")
            self._rpm_val.setText("—")
            
        self._dac_val.setText(f"{dac_raw}")

    def set_log_path(self, path: Path | None) -> None:
        self._log_label.setText(str(path) if path else "—")
