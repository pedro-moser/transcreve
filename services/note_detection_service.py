"""Guitar notes detected by Basic Pitch over the cached guitar stem.

Detection runs once per song and is cached in ``analysis/{song_id}/``. The
cache is keyed on the guitar stem file, the model checksum and the extraction
parameters, so a new separation (for example, promoting a song to "Alta
qualidade") makes it stale.
"""

import importlib.util
import json
import os
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from app_paths import analysis_dir
from services import basic_pitch as bp
from services.separation_service import CACHE_DIR as STEMS_CACHE_DIR

CACHE_DIR = analysis_dir()
CACHE_VERSION = 1
# Extracted once; the threshold slider filters these notes by score instead of
# decoding again. Upstream's onset and frame thresholds, with two changes:
# - neighbor suppression off, because it drops the lower note of a
#   simultaneous minor second, however strong it is;
# - notes from 5 frames (~58 ms) instead of 11, for fast lines.
# Lower onset thresholds split sustained notes on every ripple of the onset
# activation: on a real guitar take, 0.3 cut a 3 s G4 down to 0.07 s.
EXTRACTION = {
    "onset_threshold": 0.5,
    "frame_threshold": 0.3,
    "min_frames": 5,
    "neighbor_suppression": False,
    "min_pitch": 40,  # E2, the low string in standard tuning
    "max_pitch": 88,  # E6
}
# Recordings further than this from A440 are retuned before the model, so
# their notes do not fall between semitones.
TUNING_GATE_CENTS = 15.0


class DetectedNote(NamedTuple):
    onset: float  # seconds, song time
    offset: float
    pitch: int  # MIDI, sounding
    score: float  # mean frame activation over the note; uncalibrated


def is_available() -> bool:
    """Whether this installation can detect notes."""
    return (
        importlib.util.find_spec("onnxruntime") is not None
        and Path(bp.MODEL_PATH).is_file()
    )


def guitar_stem_path(song_id: str) -> Path:
    return STEMS_CACHE_DIR / song_id / "guitar.npy"


def stem_sample_rate(song_id: str) -> int | None:
    """Sample rate of the cached stems, or None for caches without metadata."""
    try:
        metadata = json.loads((STEMS_CACHE_DIR / song_id / "metadata.json").read_text())
        return int(metadata["sample_rate"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def has_guitar_stem(song_id: str) -> bool:
    """Whether a separation with a guitar stem is cached for ``song_id``."""
    return guitar_stem_path(song_id).is_file() and stem_sample_rate(song_id) is not None


def detect_notes(
    audio: np.ndarray, sr: int, session=None
) -> tuple[list[DetectedNote], float]:
    """Notes in ``audio`` (mono or (frames, channels)) and its tuning in cents."""
    import librosa

    mono = bp.to_model_input(audio, sr)
    cents = float(librosa.estimate_tuning(y=mono, sr=bp.SAMPLE_RATE)) * 100
    ratio = 2 ** (cents / 1200) if abs(cents) > TUNING_GATE_CENTS else 1.0
    # Reading the audio as if it were sampled at SAMPLE_RATE / ratio lowers
    # every pitch by ``cents`` and stretches time by ``ratio``; the note times
    # are scaled back to song time below.
    act = bp.infer(mono, bp.SAMPLE_RATE / ratio, session)
    notes = [
        DetectedNote(n.onset / ratio, n.offset / ratio, n.pitch, n.score)
        for n in bp.extract_notes(act, **EXTRACTION)
    ]
    return notes, cents


def cache_key(song_id: str) -> dict:
    stat = guitar_stem_path(song_id).stat()
    return {
        "version": CACHE_VERSION,
        "stem": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
        "model_sha256": bp.MODEL_SHA256,
        "extraction": EXTRACTION,
        "tuning_gate_cents": TUNING_GATE_CENTS,
    }


def _cache_path(song_id: str) -> Path:
    return CACHE_DIR / song_id / "notes.json"


def load_cached_notes(song_id: str, key: dict) -> list[DetectedNote] | None:
    """Cached notes for ``song_id`` if they were detected under ``key``."""
    try:
        data = json.loads(_cache_path(song_id).read_text())
        if data["key"] != key:
            return None
        return [
            DetectedNote(float(onset), float(offset), int(pitch), float(score))
            for onset, offset, pitch, score in data["notes"]
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_cached_notes(
    song_id: str, key: dict, tuning_cents: float, notes: list[DetectedNote]
):
    path = _cache_path(song_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "key": key,
        "tuning_cents": round(tuning_cents, 1),
        "notes": [
            [round(n.onset, 4), round(n.offset, 4), n.pitch, round(n.score, 4)]
            for n in notes
        ],
    }
    staging = path.with_name(f".{path.name}.staging")
    staging.write_text(json.dumps(data))
    os.replace(staging, path)


class _DetectWorker(QObject):
    progress = Signal(str, str)  # song_id, message
    finished = Signal(str, object)  # song_id, list[DetectedNote]
    error = Signal(str, str)  # song_id, message

    def __init__(self, song_id: str):
        super().__init__()
        self._song_id = song_id

    def run(self):
        try:
            key = cache_key(self._song_id)
            notes = load_cached_notes(self._song_id, key)
            if notes is None:
                self.progress.emit(self._song_id, "Detectando notas...")
                sr = stem_sample_rate(self._song_id)
                if sr is None:
                    raise ValueError("O cache de stems não informa a taxa de amostragem")
                stem = np.load(guitar_stem_path(self._song_id), mmap_mode="r")
                notes, cents = detect_notes(stem, sr, bp.load_session())
                save_cached_notes(self._song_id, key, cents, notes)
            self.finished.emit(self._song_id, notes)
        except Exception as e:
            self.error.emit(self._song_id, str(e))


class NoteDetectionService(QObject):
    progress = Signal(str, str)  # song_id, message
    finished = Signal(str, object)  # song_id, list[DetectedNote]
    error = Signal(str, str)  # song_id, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _DetectWorker | None = None
        # Song requested while another was being detected; the latest wins.
        self._pending: str | None = None

    @property
    def is_processing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def detect(self, song_id: str):
        """Load the cached notes for ``song_id``, or detect them."""
        if self.is_processing:
            # Even for the running song: its stems may have changed since the
            # run started, and a second run is a cache hit if they did not.
            self._pending = song_id
            return
        self._thread = QThread()
        self._worker = _DetectWorker(song_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_finished(self, song_id: str, notes: list):
        self._cleanup()
        self.finished.emit(song_id, notes)
        self._start_pending()

    def _on_error(self, song_id: str, msg: str):
        self._cleanup()
        self.error.emit(song_id, msg)
        self._start_pending()

    def _start_pending(self):
        if self._pending is not None:
            song_id, self._pending = self._pending, None
            self.detect(song_id)

    def _cleanup(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def dispose(self):
        """Wait for a running detection; Qt aborts if its thread outlives us."""
        self._pending = None
        self._cleanup()
