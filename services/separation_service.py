import json
from pathlib import Path
import shutil

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from app_paths import stems_dir

STEMS = ["vocals", "drums", "bass", "other"]
CACHE_DIR = stems_dir()


class InvalidStemCacheError(ValueError):
    """Raised when cached stem files cannot be trusted or migrated safely."""


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
            import soundfile as sf

            source_path = Path(self._file_path)
            source_info = sf.info(source_path)
            source_rate = int(source_info.samplerate)
            source_frames = int(source_info.frames)
            source_channels = int(source_info.channels)
            source_stat = source_path.stat()

            cache = CACHE_DIR / self._song_id
            self._recover_cache_transaction(cache)
            if self._check_cache(cache):
                self.progress.emit("Carregando stems do cache...")
                try:
                    stems = self._load_cache(
                        cache,
                        source_rate,
                        source_frames,
                        source_channels,
                        source_size=source_stat.st_size,
                        source_mtime_ns=source_stat.st_mtime_ns,
                    )
                except InvalidStemCacheError:
                    self.progress.emit("Cache inconsistente; separando novamente...")
                    shutil.rmtree(cache)
                else:
                    self.finished.emit(stems)
                    return

            import torch

            self.progress.emit("Carregando modelo Demucs...")
            from demucs.pretrained import get_model
            from demucs.apply import apply_model

            model = get_model("htdemucs")
            model.eval()

            self.progress.emit("Lendo áudio...")
            data, source_rate = sf.read(
                self._file_path, dtype="float32", always_2d=True
            )
            source_rate = int(source_rate)
            source_frames = int(data.shape[0])
            source_channels = int(data.shape[1])

            # Demucs operates at its own sample rate and channel count. Convert
            # the input for the model, then restore each separated stem to the
            # source format before caching or playback.
            waveform = torch.from_numpy(data.T)
            model_channels = int(getattr(model, "audio_channels", waveform.shape[0]))
            if waveform.shape[0] == 1 and model_channels == 2:
                waveform = waveform.repeat(2, 1)
            elif waveform.shape[0] != model_channels:
                raise ValueError(
                    f"Demucs requer {model_channels} canais; o áudio tem "
                    f"{waveform.shape[0]}"
                )
            if source_rate != model.samplerate:
                import torchaudio

                waveform = torchaudio.functional.resample(
                    waveform, source_rate, model.samplerate
                )

            # add batch dimension: (1, channels, frames)
            mix = waveform.unsqueeze(0)

            self.progress.emit("Separando instrumentos... (pode levar alguns minutos)")
            with torch.no_grad():
                estimates = apply_model(model, mix, device="cpu", shifts=0, split=True)
            # estimates shape: (1, n_sources, channels, frames)

            stems = {}
            for i, name in enumerate(model.sources):
                stem_tensor = estimates[0, i]
                if model.samplerate != source_rate:
                    import torchaudio

                    stem_tensor = torchaudio.functional.resample(
                        stem_tensor, model.samplerate, source_rate
                    )
                stem_np = stem_tensor.numpy().T.astype(np.float32)
                stem_np = self._fit_channel_count(stem_np, source_channels)
                stems[name] = self._fit_frame_count(stem_np, source_frames)

            self._save_cache(
                cache,
                stems,
                source_rate,
                source_frames,
                source_channels,
                source_size=source_stat.st_size,
                source_mtime_ns=source_stat.st_mtime_ns,
            )
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

    def _load_cache(
        self,
        cache_dir: Path,
        source_rate: int,
        source_frames: int,
        source_channels: int,
        *,
        source_size: int | None = None,
        source_mtime_ns: int | None = None,
    ) -> dict[str, np.ndarray]:
        metadata_path = cache_dir / "metadata.json"
        metadata = None
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text())
            except (OSError, ValueError, TypeError) as error:
                raise InvalidStemCacheError("Metadados do cache são inválidos") from error

        stems: dict[str, np.ndarray] = {}
        try:
            for name in STEMS:
                stem = np.load(cache_dir / f"{name}.npy", allow_pickle=False)
                if stem.ndim != 2 or not np.issubdtype(stem.dtype, np.number):
                    raise InvalidStemCacheError(
                        f"Stem {name} tem formato inválido: {stem.shape}"
                    )
                stems[name] = stem
        except (OSError, ValueError) as error:
            if isinstance(error, InvalidStemCacheError):
                raise
            raise InvalidStemCacheError("Não foi possível ler o cache de stems") from error

        frame_counts = {stem.shape[0] for stem in stems.values()}
        channel_counts = {stem.shape[1] for stem in stems.values()}
        if len(frame_counts) != 1 or len(channel_counts) != 1:
            raise InvalidStemCacheError("Os stems do cache têm formatos diferentes")
        cached_frames = frame_counts.pop()
        cached_channels = channel_counts.pop()

        if metadata and metadata.get("sample_rate"):
            try:
                cached_rate = int(metadata["sample_rate"])
                metadata_frames = int(metadata["frame_count"])
                metadata_channels = int(metadata.get("channels", cached_channels))
                metadata_source_size = (
                    int(metadata["source_size"])
                    if metadata.get("source_size") is not None
                    else None
                )
                metadata_source_mtime_ns = (
                    int(metadata["source_mtime_ns"])
                    if metadata.get("source_mtime_ns") is not None
                    else None
                )
            except (KeyError, TypeError, ValueError) as error:
                raise InvalidStemCacheError("Metadados do cache estão incompletos") from error
            if cached_rate <= 0:
                raise InvalidStemCacheError("Sample rate inválido no cache")
            if metadata_frames != cached_frames or metadata_channels != cached_channels:
                raise InvalidStemCacheError("Metadados não correspondem aos stems")
            if (
                source_size is not None
                and metadata_source_size is not None
                and metadata_source_size != source_size
            ):
                raise InvalidStemCacheError("O arquivo de origem foi substituído")
            if (
                source_mtime_ns is not None
                and metadata_source_mtime_ns is not None
                and metadata_source_mtime_ns != source_mtime_ns
            ):
                raise InvalidStemCacheError("O arquivo de origem foi alterado")
        else:
            # Caches created before sample-rate metadata was added contain
            # Demucs-rate audio. Infer that rate from source duration so old
            # separations can be repaired without running the model again.
            cached_rate = self._infer_sample_rate(
                cached_frames, source_rate, source_frames
            )

        if cached_rate == source_rate and cached_frames != source_frames:
            raise InvalidStemCacheError("A duração do cache não corresponde à música")
        if cached_rate != source_rate:
            converted_frames = round(cached_frames * source_rate / cached_rate)
            if abs(converted_frames - source_frames) > 2:
                raise InvalidStemCacheError("A duração do cache não corresponde à música")
            self.progress.emit(
                f"Corrigindo cache de {cached_rate} Hz para {source_rate} Hz..."
            )

        needs_rewrite = (
            metadata is None
            or int(metadata.get("version", 0)) < 3
            or cached_rate != source_rate
            or cached_channels != source_channels
            or metadata.get("source_size") is None
            or metadata.get("source_mtime_ns") is None
        )

        normalized: dict[str, np.ndarray] = {}
        for name, stem in stems.items():
            if cached_rate != source_rate:
                stem = self._resample_stem(
                    stem, cached_rate, source_rate, source_frames
                )
            stem = self._fit_channel_count(stem, source_channels)
            if stem.shape[0] != source_frames:
                raise InvalidStemCacheError("Stem normalizado ficou com duração inválida")
            normalized[name] = stem.astype(np.float32, copy=False)

        if needs_rewrite:
            self._save_cache(
                cache_dir,
                normalized,
                source_rate,
                source_frames,
                source_channels,
                source_size=source_size,
                source_mtime_ns=source_mtime_ns,
            )
        return normalized

    @staticmethod
    def _infer_sample_rate(
        cached_frames: int, source_rate: int, source_frames: int
    ) -> int:
        if source_frames <= 0:
            return source_rate
        return max(1, round(cached_frames * source_rate / source_frames))

    @staticmethod
    def _fit_frame_count(data: np.ndarray, frame_count: int) -> np.ndarray:
        if data.shape[0] > frame_count:
            return data[:frame_count]
        if data.shape[0] < frame_count:
            pad_width = [(0, frame_count - data.shape[0])]
            pad_width.extend((0, 0) for _ in data.shape[1:])
            return np.pad(data, pad_width)
        return data

    @staticmethod
    def _fit_channel_count(data: np.ndarray, channel_count: int) -> np.ndarray:
        if data.ndim != 2 or channel_count <= 0:
            raise InvalidStemCacheError("Formato de canais inválido")
        if data.shape[1] == channel_count:
            return data
        if channel_count == 1:
            return data.mean(axis=1, keepdims=True, dtype=np.float32)
        if data.shape[1] == 1:
            return np.repeat(data, channel_count, axis=1)
        raise InvalidStemCacheError(
            f"Não é possível converter {data.shape[1]} canais para {channel_count}"
        )

    @classmethod
    def _resample_stem(
        cls,
        data: np.ndarray,
        source_rate: int,
        target_rate: int,
        target_frames: int,
    ) -> np.ndarray:
        import torch
        import torchaudio

        waveform = torch.from_numpy(np.ascontiguousarray(data.T))
        with torch.no_grad():
            resampled = torchaudio.functional.resample(
                waveform, source_rate, target_rate
            )
        result = resampled.numpy().T.astype(np.float32)
        return cls._fit_frame_count(result, target_frames)

    @staticmethod
    def _staging_cache_path(cache_dir: Path) -> Path:
        return cache_dir.with_name(f".{cache_dir.name}.staging")

    @staticmethod
    def _backup_cache_path(cache_dir: Path) -> Path:
        return cache_dir.with_name(f".{cache_dir.name}.backup")

    @classmethod
    def _recover_cache_transaction(cls, cache_dir: Path):
        staging = cls._staging_cache_path(cache_dir)
        backup = cls._backup_cache_path(cache_dir)

        if not cache_dir.exists() and backup.exists():
            backup.replace(cache_dir)
        elif cache_dir.exists() and backup.exists():
            shutil.rmtree(backup)

        if staging.exists():
            shutil.rmtree(staging)

    def _save_cache(
        self,
        cache_dir: Path,
        stems: dict[str, np.ndarray],
        sample_rate: int,
        frame_count: int,
        channels: int,
        *,
        source_size: int | None = None,
        source_mtime_ns: int | None = None,
    ):
        self._recover_cache_transaction(cache_dir)
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = self._staging_cache_path(cache_dir)
        backup = self._backup_cache_path(cache_dir)
        staging.mkdir(parents=True)

        try:
            for name in STEMS:
                data = stems.get(name)
                if data is None or data.shape != (frame_count, channels):
                    raise InvalidStemCacheError(
                        f"Stem {name} não corresponde ao formato de origem"
                    )
                np.save(staging / f"{name}.npy", data.astype(np.float32, copy=False))

            metadata = {
                "version": 3,
                "sample_rate": int(sample_rate),
                "frame_count": int(frame_count),
                "channels": int(channels),
                "source_size": source_size,
                "source_mtime_ns": source_mtime_ns,
            }
            (staging / "metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n"
            )

            if cache_dir.exists():
                cache_dir.replace(backup)
            staging.replace(cache_dir)
        except Exception:
            if not cache_dir.exists() and backup.exists():
                backup.replace(cache_dir)
            if staging.exists():
                shutil.rmtree(staging)
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)


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
