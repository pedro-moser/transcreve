import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QPen
from PySide6.QtWidgets import QMenu, QToolTip

from services import fretting
import theme
from widgets.note_roll_widget import note_name
from widgets.timeline_plot import TimelinePlot, fmt_ms

FULL_OPACITY_SCORE = 0.8


class _StringAxis(pg.AxisItem):
    def __init__(self):
        super().__init__("left")
        self.names: list[str] = []

    def set_names(self, names: list[str]):
        self.names = names
        self.picture = None
        self.update()

    def tickValues(self, minVal, maxVal, size):
        return [(1, list(range(1, len(self.names) + 1)))]

    def tickStrings(self, values, scale, spacing):
        return [self.names[int(round(v)) - 1] for v in values]


class _FretNumbers(pg.GraphicsObject):
    """Fret numbers and duration lines of the notes in view, drawn in pixels."""

    FONT_PX = 12

    def __init__(self):
        super().__init__()
        self._notes: list[fretting.TabNote] = []
        self._onsets = np.zeros(0)
        self._offsets = np.zeros(0)
        self._extent = 1.0
        self._string_count = 6
        self._threshold = 0.0
        self._font = QFont()
        self._font.setPixelSize(self.FONT_PX)
        self._font.setBold(True)
        self._metrics = QFontMetricsF(self._font)

    def set_notes(self, notes: list[fretting.TabNote], threshold: float):
        self.prepareGeometryChange()
        self._notes = [n for n in notes if n.string is not None]
        self._onsets = np.array([n.onset * 1000 for n in self._notes])
        self._offsets = np.array([n.offset * 1000 for n in self._notes])
        self._strings = np.array([n.string for n in self._notes], dtype=float)
        self._extent = float(self._offsets.max()) if len(self._offsets) else 1.0
        self._threshold = threshold
        self.restyle()

    def set_string_count(self, count: int):
        self.prepareGeometryChange()
        self._string_count = count

    def restyle(self):
        """Text, sizes and colors per note, so that painting only draws."""
        self._labels = [str(n.fret) for n in self._notes]
        self._widths = [self._metrics.horizontalAdvance(t) + 6 for t in self._labels]
        self._text_colors = [self._color(n) for n in self._notes]
        self._line_pens = []
        for color in self._text_colors:
            line = pg.mkColor(theme.MAUVE)
            line.setAlphaF(0.35 + 0.4 * color.alphaF())
            self._line_pens.append(QPen(line, 3))
        self._background = pg.mkColor(theme.MANTLE)
        self._fixed_pen = QPen(pg.mkColor(theme.BLUE), 1)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0.5, self._extent, self._string_count)

    def box_width_px(self, fret: int) -> float:
        return self._metrics.horizontalAdvance(str(fret)) + 6

    def visible_indices(self) -> np.ndarray:
        vb = self.getViewBox()
        if vb is None or not len(self._notes):
            return np.zeros(0, dtype=int)
        (x0, x1), _ = vb.viewRange()
        return np.nonzero((self._offsets >= x0) & (self._onsets <= x1))[0]

    def _color(self, note: fretting.TabNote) -> QColor:
        color = pg.mkColor(theme.RED if not note.playable else theme.TEXT)
        span = max(FULL_OPACITY_SCORE - self._threshold, 1e-6)
        level = min(max((note.score - self._threshold) / span, 0.0), 1.0)
        color.setAlphaF(0.45 + 0.55 * level)
        return color

    def paint(self, painter, *args):
        indices = self.visible_indices()
        if not len(indices):
            return
        # The painter maps item to device coordinates already. (pyqtgraph's
        # deviceTransform() crashes on PySide6 6.11 with Python 3.14.)
        t = painter.transform()
        strings = self._strings[indices]
        starts = t.m11() * self._onsets[indices] + t.m21() * strings + t.dx()
        ends = t.m11() * self._offsets[indices] + t.m21() * strings + t.dx()
        rows = t.m12() * self._onsets[indices] + t.m22() * strings + t.dy()
        height = self._metrics.height()
        painter.save()
        painter.resetTransform()
        painter.setFont(self._font)
        for i, x, x_end, y in zip(indices.tolist(), starts.tolist(), ends.tolist(), rows.tolist()):
            half = self._widths[i] / 2
            if x_end > x + half:
                painter.setPen(self._line_pens[i])
                painter.drawLine(QPointF(x + half, y), QPointF(x_end, y))
            box = QRectF(x - half, y - height / 2, 2 * half, height)
            painter.fillRect(box, self._background)
            if self._notes[i].fixed:
                painter.setPen(self._fixed_pen)
                painter.drawRoundedRect(box, 3, 3)
            painter.setPen(self._text_colors[i])
            painter.drawText(box, Qt.AlignCenter, self._labels[i])
        painter.restore()

    def note_at(self, ms: float, string: int, ms_per_px: float) -> fretting.TabNote | None:
        """The note whose number or duration line is at (``ms``, ``string``)."""
        best = None
        for i in self.visible_indices():
            note = self._notes[i]
            if note.string != string:
                continue
            half = self.box_width_px(note.fret) / 2 * ms_per_px
            if self._onsets[i] - half <= ms <= max(self._offsets[i], self._onsets[i] + half):
                # The latest note that started before the cursor wins.
                if best is None or self._onsets[i] > best[0]:
                    best = (self._onsets[i], note)
        return best[1] if best else None


class TabWidget(TimelinePlot):
    """Tab of detected notes on a real time axis, without rhythm or bars.

    Draws one line per string of the tuning, guitar by default. Clicking a
    number offers the other places that note can be played.
    """

    position_chosen = Signal(object, int)  # TabNote, string
    position_cleared = Signal(object)  # TabNote

    def __init__(self, parent=None):
        super().__init__(_StringAxis(), parent)
        vb = self.getViewBox()
        vb.invertY(True)

        self._numbers = _FretNumbers()
        self._numbers.setZValue(5)
        self.addItem(self._numbers)
        vb.sigXRangeChanged.connect(lambda *_: self._numbers.update())

        self._notes: list[fretting.TabNote] = []
        self._tuning: tuple[int, ...] = ()
        self._string_lines: list[pg.InfiniteLine] = []
        self.set_tuning(fretting.STANDARD_TUNING)
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._apply_theme()
        self._update_range()

    def _apply_theme(self):
        super()._apply_theme()
        for line in self._string_lines:
            line.setPen(pg.mkPen(theme.SURFACE1, width=1))

    def refresh_theme(self):
        super().refresh_theme()
        self._numbers.restyle()

    # ── Public API ──────────────────────────────────────

    @property
    def tuning(self) -> tuple[int, ...]:
        return self._tuning

    def set_tuning(self, tuning):
        """Show the strings of ``tuning`` (open pitches from string 1).

        Notes placed for other strings are cleared.
        """
        tuning = tuple(tuning)
        if tuning == self._tuning:
            return
        self._tuning = tuning
        for line in self._string_lines:
            self.removeItem(line)
        self._string_lines = [
            pg.InfiniteLine(pos=s, angle=0, pen=pg.mkPen(theme.SURFACE1, width=1))
            for s in range(1, len(tuning) + 1)
        ]
        for line in self._string_lines:
            line.setZValue(-10)
            self.addItem(line)
        self.getPlotItem().getAxis("left").set_names(fretting.string_names(tuning))
        self._numbers.set_string_count(len(tuning))
        self.setYRange(0.4, len(tuning) + 0.6, padding=0)
        self.clear_notes()

    def set_notes(self, notes: list[fretting.TabNote], threshold: float = 0.0):
        self._notes = notes
        self._numbers.set_notes(notes, threshold)

    def clear_notes(self):
        self.set_notes([])

    @property
    def notes(self) -> list[fretting.TabNote]:
        return self._notes

    def note_at(self, ms: float, y: float) -> fretting.TabNote | None:
        string = int(round(y))
        if not 1 <= string <= len(self._tuning):
            return None
        return self._numbers.note_at(ms, string, self._ms_per_pixel())

    def alternatives(self, note: fretting.TabNote) -> list[fretting.Position]:
        return fretting.positions(note.pitch, self._tuning)

    # ── Mouse ───────────────────────────────────────────

    def _note_under(self, widget_pos) -> fretting.TabNote | None:
        vb = self.getViewBox()
        scene_pos = self.mapToScene(widget_pos)
        if not vb.sceneBoundingRect().contains(scene_pos):
            return None
        point = vb.mapSceneToView(scene_pos)
        return self.note_at(point.x(), point.y())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            note = self._note_under(event.position().toPoint())
            if note is not None:
                self._open_menu(note, event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def _open_menu(self, note: fretting.TabNote, global_pos):
        names = fretting.string_names(self._tuning)
        menu = QMenu(self)
        menu.addSection(note_name(note.pitch))
        for position in self.alternatives(note):
            action = menu.addAction(
                f"Corda {position.string} ({names[position.string - 1]}) · casa {position.fret}"
            )
            action.setCheckable(True)
            action.setChecked(position.string == note.string)
            action.setData(position.string)
        clear = None
        if note.fixed:
            menu.addSeparator()
            clear = menu.addAction("Voltar à posição automática")
        chosen = self._exec_menu(menu, global_pos)
        if chosen is None:
            return
        if chosen is clear:
            self.position_cleared.emit(note)
        else:
            self.position_chosen.emit(note, int(chosen.data()))

    def _exec_menu(self, menu: QMenu, global_pos):
        return menu.exec(global_pos)

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
        details = [
            note_name(note.pitch),
            f"corda {note.string}, casa {note.fret}",
            fmt_ms(note.onset * 1000, 2),
            f"score {note.score:.2f}",
        ]
        if note.fixed:
            details.append("posição fixada")
        if not note.playable:
            details.append("não cabe na digitação do acorde")
        QToolTip.showText(QCursor.pos(), " · ".join(details), self)
