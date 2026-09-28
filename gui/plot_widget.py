"""
Real-time Plot Widget.

Shows two views:
  1. RPM and Torque vs Time  (live strip-chart during a run)
  2. RPM vs Torque (N·m)     (scatter / XY curve — the dyno curve)

Uses pyqtgraph for fast, OpenGL-accelerated rendering.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from modules.data_model import Sample

# -------------------------------------------------------------------------
# Global pyqtgraph style
# -------------------------------------------------------------------------
pg.setConfigOption("background", "#1e1e2e")
pg.setConfigOption("foreground", "#cdd6f4")
pg.setConfigOption("antialias", True)


_TORQUE_COLOR = "#f38ba8"    # red-pink
_RPM_COLOR    = "#89b4fa"    # blue
_CURVE_COLOR  = "#a6e3a1"    # green


class TimePlotWidget(QWidget):
    """
    Strip chart: RPM (left axis, blue) and Torque (right axis, pink) vs Time.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(title="RPM & Torque vs Time")
        self._plot.setLabel("bottom", "Time", units="s")
        self._plot.setLabel("left", "RPM", color=_RPM_COLOR)
        self._plot.addLegend(offset=(10, 10))
        self._plot.showGrid(x=True, y=True, alpha=0.3)

        # ViewBox for torque on secondary Y
        self._vb_torque = pg.ViewBox()
        self._plot.scene().addItem(self._vb_torque)
        ax_right = pg.AxisItem("right")
        ax_right.setLabel("Torque", units="N·m", color=_TORQUE_COLOR)
        self._plot.getPlotItem().layout.addItem(ax_right, 2, 3)
        ax_right.linkToView(self._vb_torque)
        self._vb_torque.setXLink(self._plot)
        self._plot.getViewBox().sigResized.connect(self._sync_views)

        # Curves
        self._rpm_curve = self._plot.plot(
            [], [], pen=pg.mkPen(_RPM_COLOR, width=2), name="RPM"
        )
        self._torque_curve = pg.PlotDataItem(
            [], [],
            pen=pg.mkPen(_TORQUE_COLOR, width=2),
            name="Torque (N·m)",
        )
        self._vb_torque.addItem(self._torque_curve)

        layout.addWidget(self._plot)

    def _sync_views(self) -> None:
        self._vb_torque.setGeometry(self._plot.getViewBox().sceneBoundingRect())
        self._vb_torque.linkedViewChanged(self._plot.getViewBox(), self._vb_torque.XAxis)

    def update_data(self, times: np.ndarray, rpms: np.ndarray, torques: np.ndarray) -> None:
        self._rpm_curve.setData(times, rpms)
        self._torque_curve.setData(times, torques)

    def clear(self) -> None:
        self._rpm_curve.setData([], [])
        self._torque_curve.setData([], [])


class DynoCurveWidget(QWidget):
    """
    Dyno curve: RPM vs Torque (N·m) — the classic dynamometer output.
    Each point is a scatter dot; a line connects them in measurement order.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(title="Dyno Curve — RPM vs Torque")
        self._plot.setLabel("bottom", "Torque", units="N·m")
        self._plot.setLabel("left", "Speed", units="RPM")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.addLegend(offset=(10, 10))

        self._line = self._plot.plot(
            [], [],
            pen=pg.mkPen(_CURVE_COLOR, width=2),
            name="Dyno curve",
        )
        self._scatter = pg.ScatterPlotItem(
            size=5,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(_CURVE_COLOR + "aa"),
        )
        self._plot.addItem(self._scatter)

        layout.addWidget(self._plot)

    def update_data(self, torques: np.ndarray, rpms: np.ndarray) -> None:
        self._line.setData(torques, rpms)
        self._scatter.setData(torques, rpms)

    def clear(self) -> None:
        self._line.setData([], [])
        self._scatter.setData([], [])


class PlotPanel(QWidget):
    """
    Tabbed container for both plot views.
    Call update_samples() to push new data from any thread (via Qt signals).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        self._time_plot = TimePlotWidget()
        self._dyno_plot = DynoCurveWidget()
        tabs.addTab(self._time_plot, "Time Chart")
        tabs.addTab(self._dyno_plot, "Dyno Curve")
        layout.addWidget(tabs)

    def update_samples(self, samples: list[Sample]) -> None:
        """Rebuild plots from the full list of samples."""
        if not samples:
            return
        times   = np.array([s.elapsed_s   for s in samples])
        rpms    = np.array([s.rpm         for s in samples])
        torques = np.array([s.torque_nm   for s in samples])

        self._time_plot.update_data(times, rpms, torques)
        self._dyno_plot.update_data(torques, rpms)

    def clear(self) -> None:
        self._time_plot.clear()
        self._dyno_plot.clear()
