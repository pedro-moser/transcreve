import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 24 chord templates: 12 major + 12 minor
# Each is a 12-element binary vector (chroma)
_TEMPLATES: list[tuple[str, np.ndarray]] = []

def _build_templates():
    major = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=np.float32)  # root, M3, P5
    minor = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=np.float32)  # root, m3, P5
    for i, name in enumerate(NOTE_NAMES):
        _TEMPLATES.append((name, np.roll(major, i)))
        _TEMPLATES.append((f"{name}m", np.roll(minor, i)))
    # normalize templates
    for j in range(len(_TEMPLATES)):
        name, vec = _TEMPLATES[j]
        _TEMPLATES[j] = (name, vec / np.linalg.norm(vec))

_build_templates()


class _ChromaWorker(QObject):
    finished = Signal(object)  # chroma ndarray or None

    def __init__(self, data: np.ndarray, sr: int):
        super().__init__()
        self._data = data
        self._sr = sr

    def run(self):
        try:
            import librosa
            mono = self._data.mean(axis=1) if self._data.ndim == 2 else self._data
            chroma = librosa.feature.chroma_cqt(
                y=mono.astype(np.float32), sr=self._sr, hop_length=512
            )
            self.finished.emit(chroma)
        except Exception as e:
            print(f"Chroma error: {e}")
            self.finished.emit(None)


class ChordService(QObject):
    ready = Signal()

    HOP_LENGTH = 512

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chroma: np.ndarray | None = None
        self._sr: int = 44100
        self._thread: QThread | None = None
        self._worker: _ChromaWorker | None = None

    @property
    def is_ready(self) -> bool:
        return self._chroma is not None

    def analyze(self, data: np.ndarray, sr: int):
        """Start background chroma analysis."""
        self._chroma = None
        self._sr = sr
        self._cancel()

        self._thread = QThread()
        self._worker = _ChromaWorker(data, sr)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, chroma):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None
        if chroma is not None:
            self._chroma = chroma
            self.ready.emit()

    def _cancel(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def detect_at(self, ms: int) -> str:
        """Detect chord at given position in milliseconds."""
        if self._chroma is None:
            return "..."
        frame = int(ms / 1000 * self._sr / self.HOP_LENGTH)
        frame = max(0, min(frame, self._chroma.shape[1] - 1))

        chroma_vec = self._chroma[:, frame].astype(np.float32)
        norm = np.linalg.norm(chroma_vec)
        if norm < 0.01:
            return "N.C."  # no chord / silence
        chroma_vec = chroma_vec / norm

        best_score = -1.0
        best_name = "?"
        for name, template in _TEMPLATES:
            score = float(np.dot(chroma_vec, template))
            if score > best_score:
                best_score = score
                best_name = name

        return best_name

    def dispose(self):
        self._cancel()
        self._chroma = None
