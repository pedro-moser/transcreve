import json
from pathlib import Path

import numpy as np
import torch
from PySide6.QtCore import QObject, QThread, Signal

STEMS = ["vocals", "drums", "bass", "other"]
CACHE_DIR = Path.home() / ".local" / "share" / "transcreve" / "stems"


class _SepWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)  # {name: ndarray} or empty on error
    error = Signal(str)

    def __init__(self, file_path: str, song_id: str):
        super().__init__()
        self._file_path = file_path
        self._song_id = song_id

    def run(self):
        try:
            cache = CACHE_DIR / self._song_id
            if self._check_cache(cache):
                self.progress.emit("Carregando stems do cache...")
                stems = self._load_cache(cache)
                self.finished.emit(stems)
                return

            self.progress.emit("Carregando modelo Demucs...")
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
            import soundfile as sf

            model = get_model("htdemucs")
            model.eval()

            self.progress.emit("Lendo áudio...")
            data, sr = sf.read(self._file_path, dtype="float32", always_2d=True)

            # resample if needed
            if sr != model.samplerate:
                import torchaudio
                waveform = torch.from_numpy(data.T)  # (channels, frames)
                waveform = torchaudio.functional.resample(waveform, sr, model.samplerate)
            else:
                waveform = torch.from_numpy(data.T)

            # add batch dimension: (1, channels, frames)
            mix = waveform.unsqueeze(0)

            self.progress.emit("Separando instrumentos... (pode levar alguns minutos)")
            with torch.no_grad():
                estimates = apply_model(model, mix, device="cpu", shifts=0, split=True)
            # estimates shape: (1, n_sources, channels, frames)

            stems = {}
            for i, name in enumerate(model.sources):
                stem_np = estimates[0, i].numpy().T  # (frames, channels)
                stems[name] = stem_np.astype(np.float32)

            # save cache
            self._save_cache(cache, stems)
            self.progress.emit("Pronto!")
            self.finished.emit(stems)

        except Exception as e:
            self.error.emit(str(e))

    def _check_cache(self, cache_dir: Path) -> bool:
        if not cache_dir.exists():
            return False
        for name in STEMS:
            if not (cache_dir / f"{name}.npy").exists():
                return False
        return True

    def _load_cache(self, cache_dir: Path) -> dict:
        stems = {}
        for name in STEMS:
            stems[name] = np.load(cache_dir / f"{name}.npy")
        return stems

    def _save_cache(self, cache_dir: Path, stems: dict):
        cache_dir.mkdir(parents=True, exist_ok=True)
        for name, data in stems.items():
            np.save(cache_dir / f"{name}.npy", data)


class SeparationService(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _SepWorker | None = None

    @property
    def is_processing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def separate(self, file_path: str, song_id: str):
        if self.is_processing:
            return
        self._thread = QThread()
        self._worker = _SepWorker(file_path, song_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_finished(self, stems: dict):
        self._cleanup()
        self.finished.emit(stems)

    def _on_error(self, msg: str):
        self._cleanup()
        self.error.emit(msg)

    def _cleanup(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def has_cache(self, song_id: str) -> bool:
        cache = CACHE_DIR / song_id
        return all((cache / f"{n}.npy").exists() for n in STEMS)
