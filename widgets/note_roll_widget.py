import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip

from services.chord_service import NOTE_NAMES
import theme
from widgets.timeline_plot import TimelinePlot, fmt_ms

_BLACK_KEYS = {1, 3, 6, 8, 10}


def note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


class _PitchAxis(pg.AxisItem):
    def tickValues(self, minVal, maxVal, size):
        lo, hi = int(np.ceil(minVal)), int(np.floor(maxVal))
        pitches = range(lo, hi + 1)
        return [
            (12, [p for p in pitches if p % 12 == 0]),
            (1, [p for p in pitches if p % 12 != 0 and p % 12 not in _BLACK_KEYS]),
        ]

    def tickStrings(self, values, scale, spacing):
        return [note_name(int(round(v))) for v in values]


class NoteRollWidget(TimelinePlot):
    """Piano-roll of detected notes."""

    MIN_PITCH_SPAN = 24
    # Opacity follows the score in a few steps: one bar item per step keeps a
    # dense song cheap to repaint while the view scrolls.
    OPACITY_STEPS = 5
    FULL_OPACITY_SCORE = 0.8

    def __init__(self, parent=None):
        super().__init__(_PitchAxis("left"), parent)
        self._threshold = 0.35
        # columns: onset ms, offset ms, pitch, score
        self._notes = np.zeros((0, 4))
        self._visible = np.zeros((0, 4))
        self._key_rows: pg.BarGraphItem | None = None
        self._bars: list[pg.BarGraphItem] = []

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._apply_theme()
        self._set_pitch_range(52, 76)
        self._update_range()

    def refresh_theme(self):
        super().refresh_theme()
        self._draw_key_rows()
        self._draw_notes()

    # ── Public API ──────────────────────────────────────

    def set_duration(self, ms: int):
        super().set_duration(ms)
        self._draw_key_rows()

    def set_notes(self, notes):
        """Show ``notes`` (onset/offset in seconds, pitch, score)."""
        self._notes = np.array(
            [(n.onset * 1000, n.offset * 1000, n.pitch, n.score) for n in notes],
            dtype=float,
        ).reshape(-1, 4)
        if len(self._notes):
            self._set_pitch_range(self._notes[:, 2].min(), self._notes[:, 2].max())
        self._draw_notes()

    def clear_notes(self):
        self.set_notes([])

    def set_threshold(self, threshold: float):
        self._threshold = threshold
        self._draw_notes()

    @property
    def visible_note_count(self) -> int:
        return len(self._visible)

    def note_at(self, ms: float, pitch: float):
        """The shown note under (``ms``, ``pitch``), as an array row, or None."""
        p = round(pitch)
        hits = self._visible[
            (self._visible[:, 2] == p)
            & (self._visible[:, 0] <= ms)
            & (self._visible[:, 1] >= ms)
        ]
        return hits[np.argmax(hits[:, 3])] if len(hits) else None

    # ── Drawing ─────────────────────────────────────────

    def _set_pitch_range(self, lo: float, hi: float):
        lo, hi = int(lo) - 1, int(hi) + 1
        missing = self.MIN_PITCH_SPAN - (hi - lo)
        if missing > 0:
            lo -= missing // 2
            hi += missing - missing // 2
        self._pitch_range = (lo, hi)
        self.setYRange(lo - 0.5, hi + 0.5, padding=0)
        self._draw_key_rows()

    def _draw_key_rows(self):
        if self._key_rows is not None:
            self.removeItem(self._key_rows)
            self._key_rows = None
        lo, hi = self._pitch_range
        rows = [p for p in range(lo, hi + 1) if p % 12 in _BLACK_KEYS]
        if not rows or self._duration_ms <= 0:
            return
        color = pg.mkColor(theme.SURFACE0)
        color.setAlpha(110)
        self._key_rows = pg.BarGraphItem(
            x0=0, x1=self._duration_ms, y0=np.array(rows) - 0.5, height=1.0,
            brush=pg.mkBrush(color), pen=pg.mkPen(None),
        )
        self._key_rows.setZValue(-10)
        self.addItem(self._key_rows)

    def _draw_notes(self):
        for bar in self._bars:
            self.removeItem(bar)
        self._bars.clear()
        self._visible = self._notes[self._notes[:, 3] >= self._threshold]
        if not len(self._visible):
            return
        span = max(self.FULL_OPACITY_SCORE - self._threshold, 1e-6)
        level = np.clip((self._visible[:, 3] - self._threshold) / span, 0, 1)
        steps = np.minimum((level * self.OPACITY_STEPS).astype(int), self.OPACITY_STEPS - 1)
        for step in range(self.OPACITY_STEPS):
            rows = self._visible[steps == step]
            if not len(rows):
                continue
            color = pg.mkColor(theme.MAUVE)
            color.setAlphaF(0.3 + 0.7 * step / (self.OPACITY_STEPS - 1))
            bar = pg.BarGraphItem(
                x0=rows[:, 0], x1=rows[:, 1], y0=rows[:, 2] - 0.4, height=0.8,
                brush=pg.mkBrush(color), pen=pg.mkPen(None),
            )
            bar.setZValue(step)
            self.addItem(bar)
            self._bars.append(bar)

    # ── Mouse ───────────────────────────────────────────

    def _on_mouse_moved(self, scene_pos):
        vb = self.getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            QToolTip.hideText()
            return
        point = vb.mapSceneToView(scene_pos)
        note = self.note_at(point.x(), point.y())
        if note is None:
            QToolTip.hideText()
            return
        onset, _, pitch, score = note
        QToolTip.showText(
            QCursor.pos(),
            f"{note_name(int(pitch))} · {fmt_ms(onset, 2)} · score {score:.2f}",
            self,
        )
