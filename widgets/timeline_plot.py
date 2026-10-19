import pyqtgraph as pg

import theme


def fmt_ms(ms: float, decimals: int = 0) -> str:
    total_s = max(ms, 0) / 1000
    m = int(total_s) // 60
    s = total_s - m * 60
    if decimals:
        return f"{m}:{s:0{3 + decimals}.{decimals}f}"
    return f"{m}:{int(s):02d}"


class _TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [fmt_ms(v, 1 if spacing < 1000 else 0) for v in values]


class TimelinePlot(pg.PlotWidget):
    """Detail view of the song, zoomed around the playhead or the loop.

    The x axis is in milliseconds, like the waveform. While the A–B loop is on
    the view shows the loop; otherwise it follows the playhead and the mouse
    wheel sets how many seconds it shows.
    """

    MIN_WINDOW_MS = 2_000
    MAX_WINDOW_MS = 60_000
    DEFAULT_WINDOW_MS = 8_000
    PLAYHEAD_FRACTION = 0.3  # playhead position in the window while following

    def __init__(self, left_axis: pg.AxisItem, parent=None):
        super().__init__(
            parent,
            background=theme.MANTLE,
            axisItems={"left": left_axis, "bottom": _TimeAxis("bottom")},
        )
        self._duration_ms = 0
        self._position_ms = 0
        self._window_ms = self.DEFAULT_WINDOW_MS
        self._loop: tuple[int, int] | None = None

        self.setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.getPlotItem().setContentsMargins(0, 0, 4, 0)
        self.getViewBox().setDefaultPadding(0)
        self.getViewBox().disableAutoRange()

        self._loop_lines = [
            pg.InfiniteLine(angle=90, pen=pg.mkPen(theme.PEACH, width=1)) for _ in range(2)
        ]
        for line in self._loop_lines:
            line.setZValue(8)
            line.hide()
            self.addItem(line)

        self._playhead = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(theme.TEXT, width=2))
        self._playhead.setZValue(10)
        self.addItem(self._playhead)
        self.setMinimumHeight(140)

    def _apply_theme(self):
        self.setBackground(theme.MANTLE)
        self.setStyleSheet(f"border: none; background-color: {theme.MANTLE};")
        for axis in ("left", "bottom"):
            item = self.getPlotItem().getAxis(axis)
            item.setPen(pg.mkPen(theme.SURFACE1))
            item.setTextPen(pg.mkPen(theme.SUBTEXT0))
        for line in self._loop_lines:
            line.setPen(pg.mkPen(theme.PEACH, width=1))
        self._playhead.setPen(pg.mkPen(theme.TEXT, width=2))

    def refresh_theme(self):
        self._apply_theme()

    # ── Public API ──────────────────────────────────────

    @property
    def window_ms(self) -> int:
        return self._window_ms

    @window_ms.setter
    def window_ms(self, ms: int):
        self._window_ms = int(min(self.MAX_WINDOW_MS, max(self.MIN_WINDOW_MS, ms)))
        self._update_range()

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self._update_range()

    def set_position(self, ms: int):
        self._position_ms = ms
        self._playhead.setPos(ms)
        if self._loop is None:
            self._update_range()

    def set_loop_region(self, start_ms: int | None, end_ms: int | None, enabled: bool):
        if enabled and start_ms is not None and end_ms is not None and end_ms > start_ms:
            self._loop = (start_ms, end_ms)
            for line, pos in zip(self._loop_lines, self._loop):
                line.setPos(pos)
                line.show()
        else:
            self._loop = None
            for line in self._loop_lines:
                line.hide()
        self._update_range()

    def _update_range(self):
        if self._loop is not None:
            start, end = self._loop
            pad = max(200, 0.03 * (end - start))
            self.setXRange(start - pad, end + pad, padding=0)
            return
        width = self._window_ms
        left = self._position_ms - self.PLAYHEAD_FRACTION * width
        left = max(0, min(left, self._duration_ms - width))
        self.setXRange(left, left + width, padding=0)

    def _ms_per_pixel(self) -> float:
        (x0, x1), _ = self.getViewBox().viewRange()
        return (x1 - x0) / max(self.getViewBox().width(), 1)

    # ── Mouse ───────────────────────────────────────────

    def wheelEvent(self, event):
        if self._loop is not None:
            event.ignore()
            return
        factor = 0.8 if event.angleDelta().y() > 0 else 1.25
        self.window_ms = self._window_ms * factor
        event.accept()
