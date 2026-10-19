"""Notes detected by Basic Pitch over the cached stems.

Detection runs once per song and stem and is cached in ``analysis/{song_id}/``.
The cache is keyed on the stem file, the model checksum and the extraction
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
# Stems whose notes can be detected, and the MIDI range decoded from each.
# EXTRACTION holds the guitar's; Basic Pitch covers A0 (21) to C8 (108).
PITCH_RANGES = {
    "guitar": (EXTRACTION["min_pitch"], EXTRACTION["max_pitch"]),
    "bass": (28, 67),  # E1–G4: four strings, 24 frets
    "piano": (21, 108),
    "other": (21, 108),
}
NOTE_STEMS = tuple(PITCH_RANGES)
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


def extraction(stem: str) -> dict:
    """Decoding parameters for ``stem``: EXTRACTION over the stem's range."""
    low, high = PITCH_RANGES[stem]
    return {**EXTRACTION, "min_pitch": low, "max_pitch": high}


def stem_path(song_id: str, stem: str) -> Path:
    return STEMS_CACHE_DIR / song_id / f"{stem}.npy"


def stem_sample_rate(song_id: str) -> int | None:
    """Sample rate of the cached stems, or None for caches without metadata."""
    try:
        metadata = json.loads((STEMS_CACHE_DIR / song_id / "metadata.json").read_text())
        return int(metadata["sample_rate"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def note_stems(song_id: str) -> list[str]:
    """Cached stems of ``song_id`` whose notes can be detected, in NOTE_STEMS order."""
    if stem_sample_rate(song_id) is None:
        return []
    return [stem for stem in NOTE_STEMS if stem_path(song_id, stem).is_file()]


def detect_notes(
    audio: np.ndarray, sr: int, session=None, stem: str = "guitar"
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
        for n in bp.extract_notes(act, **extraction(stem))
    ]
    return notes, cents


def cache_key(song_id: str, stem: str) -> dict:
    stat = stem_path(song_id, stem).stat()
    return {
        "version": CACHE_VERSION,
        "stem": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
        "model_sha256": bp.MODEL_SHA256,
        "extraction": extraction(stem),
        "tuning_gate_cents": TUNING_GATE_CENTS,
    }


def _cache_path(song_id: str, stem: str) -> Path:
    # The guitar keeps the name from when it was the only stem analyzed, so
    # songs analyzed back then are not detected again.
    name = "notes.json" if stem == "guitar" else f"notes-{stem}.json"
    return CACHE_DIR / song_id / name


def load_cached_notes(song_id: str, stem: str, key: dict) -> list[DetectedNote] | None:
    """Cached notes for ``stem`` of ``song_id`` if they were detected under ``key``."""
    try:
        data = json.loads(_cache_path(song_id, stem).read_text())
        if data["key"] != key:
            return None
        return [
            DetectedNote(float(onset), float(offset), int(pitch), float(score))
            for onset, offset, pitch, score in data["notes"]
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_cached_notes(
    song_id: str, stem: str, key: dict, tuning_cents: float, notes: list[DetectedNote]
):
    path = _cache_path(song_id, stem)
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
    progress = Signal(str, str, str)  # song_id, stem, message
    finished = Signal(str, str, object)  # song_id, stem, list[DetectedNote]
    error = Signal(str, str, str)  # song_id, stem, message

    def __init__(self, song_id: str, stem: str):
        super().__init__()
        self._song_id = song_id
        self._stem = stem

    def run(self):
        song_id, stem = self._song_id, self._stem
        try:
            key = cache_key(song_id, stem)
            notes = load_cached_notes(song_id, stem, key)
            if notes is None:
                self.progress.emit(song_id, stem, "Detectando notas...")
                sr = stem_sample_rate(song_id)
                if sr is None:
                    raise ValueError("O cache de stems não informa a taxa de amostragem")
                audio = np.load(stem_path(song_id, stem), mmap_mode="r")
                notes, cents = detect_notes(audio, sr, bp.load_session(), stem)
                save_cached_notes(song_id, stem, key, cents, notes)
            self.finished.emit(song_id, stem, notes)
        except Exception as e:
            self.error.emit(song_id, stem, str(e))


class NoteDetectionService(QObject):
    progress = Signal(str, str, str)  # song_id, stem, message
    finished = Signal(str, str, object)  # song_id, stem, list[DetectedNote]
    error = Signal(str, str, str)  # song_id, stem, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _DetectWorker | None = None
        # (song_id, stem) requested while another was being detected; the
        # latest wins.
        self._pending: tuple[str, str] | None = None

    @property
    def is_processing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def detect(self, song_id: str, stem: str):
        """Load the cached notes for ``stem`` of ``song_id``, or detect them."""
        if self.is_processing:
            # Even for the running song and stem: its stems may have changed
            # since the run started, and a second run is a cache hit if not.
            self._pending = (song_id, stem)
            return
        self._thread = QThread()
        self._worker = _DetectWorker(song_id, stem)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_finished(self, song_id: str, stem: str, notes: list):
        self._cleanup()
        self.finished.emit(song_id, stem, notes)
        self._start_pending()

    def _on_error(self, song_id: str, stem: str, msg: str):
        self._cleanup()
        self.error.emit(song_id, stem, msg)
        self._start_pending()

    def _start_pending(self):
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self.detect(*pending)

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
