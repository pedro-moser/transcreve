import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal

from models.section import Section
import theme

pg.setConfigOptions(antialias=False, useOpenGL=False)


class WaveformWidget(pg.PlotWidget):
    """Waveform display with playhead, loop region, section markers, and cue point."""

    seek_requested = Signal(int)
    loop_region_changed = Signal(int, int)

    MAX_POINTS = 3000

    def __init__(self, parent=None):
        super().__init__(parent, background=theme.MANTLE)

        self._duration_ms: int = 0
        self._sr: int = 44100
        self._dragging = False

        self.setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.getPlotItem().hideAxis("left")
        self.getPlotItem().hideAxis("bottom")
        self.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.getViewBox().setDefaultPadding(0)

        self._curve = self.plot([], [], pen=pg.mkPen(theme.BLUE, width=1))

        self._loop_region = pg.LinearRegionItem(
            values=[0, 0],
            orientation="vertical",
            brush=pg.mkBrush(250, 179, 135, 40),
            pen=pg.mkPen(theme.PEACH, width=1),
            movable=True,
        )
        self._loop_region.setZValue(5)
        self._loop_region.hide()
        self.addItem(self._loop_region)
        self._loop_region.sigRegionChangeFinished.connect(self._on_loop_region_changed)

        self._section_lines: list[pg.InfiniteLine] = []

        self._cue_line = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen(theme.TEAL, width=2, style=Qt.DashLine),
        )
        self._cue_line.setZValue(8)
        self._cue_line.hide()
        self.addItem(self._cue_line)

        self._playhead = pg.InfiniteLine(
            pos=0, angle=90,
            pen=pg.mkPen("#FFFFFF", width=2),
        )
        self._playhead.setZValue(10)
        self.addItem(self._playhead)

        self.setFixedHeight(120)
        self._apply_theme()

    def _apply_theme(self):
        self.setBackground(theme.MANTLE)
        self.setStyleSheet(f"border: none; background-color: {theme.MANTLE};")
        self._curve.setPen(pg.mkPen(theme.BLUE, width=1))
        self._cue_line.setPen(pg.mkPen(theme.TEAL, width=2, style=Qt.DashLine))

    def refresh_theme(self):
        self._apply_theme()

    # ── Public API ──────────────────────────────────────

    def load_waveform(self, data: np.ndarray, sr: int, duration_ms: int):
        self._sr = sr
        self._duration_ms = duration_ms

        if data.ndim == 2:
            mono = data.mean(axis=1)
        else:
            mono = data

        n = len(mono)
        if n > self.MAX_POINTS:
            step = n // self.MAX_POINTS
            trimmed = mono[: step * self.MAX_POINTS]
            chunks = trimmed.reshape(-1, step)
            envelope = np.max(np.abs(chunks), axis=1)
        else:
            envelope = np.abs(mono)

        x = np.linspace(0, duration_ms, len(envelope))
        self._curve.setData(x, envelope)
        self.getViewBox().setLimits(xMin=0, xMax=duration_ms, yMin=0, yMax=1)
        self.setXRange(0, duration_ms, padding=0)
        y_max = float(np.max(envelope) * 1.05) if len(envelope) > 0 else 1.0
        self.setYRange(0, y_max, padding=0)
        self._playhead.setPos(0)

    def set_position(self, ms: int):
        if not self._dragging:
            self._playhead.setPos(ms)

    def set_loop_region(self, start_ms: int | None, end_ms: int | None, enabled: bool):
        if enabled and start_ms is not None and end_ms is not None:
            self._loop_region.blockSignals(True)
            self._loop_region.setRegion([start_ms, end_ms])
            self._loop_region.blockSignals(False)
            self._loop_region.show()
        else:
            self._loop_region.hide()

    def set_sections(self, sections: list[Section]):
        for line in self._section_lines:
            self.removeItem(line)
        self._section_lines.clear()

        for sec in sorted(sections, key=lambda s: s.start_ms):
            line = pg.InfiniteLine(
                pos=sec.start_ms, angle=90,
                pen=pg.mkPen(sec.color_hex, width=1.5),
                label=sec.name,
                labelOpts={
                    "position": 0.95,
                    "color": sec.color_hex,
                    "fill": pg.mkBrush(24, 24, 37, 180),
                    "movable": False,
                },
            )
            line.setZValue(6)
            self.addItem(line)
            self._section_lines.append(line)

    def set_cue_point(self, ms: int | None):
        if ms is not None:
            self._cue_line.setPos(ms)
            self._cue_line.show()
        else:
            self._cue_line.hide()

    # ── Mouse events ────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._duration_ms > 0:
            item = self.itemAt(event.pos())
            if item is self._loop_region or (
                hasattr(self._loop_region, "lines")
                and item in self._loop_region.lines
            ):
                super().mousePressEvent(event)
                return
            self._dragging = True
            ms = self._pos_to_ms(event.pos())
            self._playhead.setPos(ms)
            self.seek_requested.emit(ms)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._duration_ms > 0:
            ms = self._pos_to_ms(event.pos())
            self._playhead.setPos(ms)
            self.seek_requested.emit(ms)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
        else:
            super().mouseReleaseEvent(event)

    def _pos_to_ms(self, pos) -> int:
        vb = self.getViewBox()
        scene_pos = self.mapToScene(pos)
        data_pos = vb.mapSceneToView(scene_pos)
        ms = int(data_pos.x())
        return max(0, min(ms, self._duration_ms))

    def _on_loop_region_changed(self):
        region = self._loop_region.getRegion()
        start_ms = max(0, int(region[0]))
        end_ms = min(self._duration_ms, int(region[1]))
        self.loop_region_changed.emit(start_ms, end_ms)
