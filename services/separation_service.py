import json
from pathlib import Path
import shutil

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from app_paths import stems_dir

DEFAULT_MODEL = "htdemucs_6s"
HQ_MODEL = "bs_roformer_sw"
# Higher rank separates better. A cached result is reused whenever it is at
# least as good as the requested model, so choosing "Padrão" never discards a
# high-quality separation.
MODEL_RANK = {"htdemucs": 0, DEFAULT_MODEL: 1, HQ_MODEL: 2}
STEMS = ["vocals", "drums", "bass", "guitar", "piano", "other"]
# Caches written by the 4-stem htdemucs model are still loadable; the UI offers
# to re-separate them so guitar and piano get their own stems.
LEGACY_STEMS = ["vocals", "drums", "bass", "other"]
STEM_SETS = (STEMS, LEGACY_STEMS)
CACHE_DIR = stems_dir()


class InvalidStemCacheError(ValueError):
    """Raised when cached stem files cannot be trusted or migrated safely."""


class _SepWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict, str)  # {name: ndarray}, model that produced them
    error = Signal(str)

    def __init__(
        self,
        file_path: str,
        song_id: str,
        model: str = DEFAULT_MODEL,
    ):
        super().__init__()
        self._file_path = file_path
        self._song_id = song_id
        self._model = model

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
            cached = cached_model(cache)
            if cached is not None and MODEL_RANK[cached] >= MODEL_RANK[self._model]:
                self.progress.emit("Carregando stems do cache...")
                try:
                    stems = self._load_cache(
                        cache,
                        source_rate,
                        source_frames,
                        source_channels,
                        source_size=source_stat.st_size,
                        source_mtime_ns=source_stat.st_mtime_ns,
                        names=cached_stem_names(cache),
                        model=cached,
                    )
                except InvalidStemCacheError:
                    self.progress.emit("Cache inconsistente; separando novamente...")
                    shutil.rmtree(cache)
                else:
                    self.finished.emit(stems, cached)
                    return

            import torch

            self.progress.emit("Lendo áudio...")
            data, source_rate = sf.read(
                self._file_path, dtype="float32", always_2d=True
            )
            source_rate = int(source_rate)
            source_frames = int(data.shape[0])
            source_channels = int(data.shape[1])

            # Both models are stereo and run at their own sample rate. Convert
            # the input for the model, then restore each separated stem to the
            # source format before caching or playback.
            waveform = torch.from_numpy(data.T)
            if waveform.shape[0] == 1:
                waveform = waveform.repeat(2, 1)
            elif waveform.shape[0] != 2:
                raise ValueError(
                    f"A separação requer áudio mono ou estéreo; o áudio tem "
                    f"{waveform.shape[0]} canais"
                )

            if self._model == HQ_MODEL:
                sources, model_rate, estimates = self._separate_roformer(
                    waveform, source_rate
                )
            else:
                sources, model_rate, estimates = self._separate_demucs(
                    waveform, source_rate
                )
            # estimates shape: (n_sources, channels, frames) at model_rate

            stems = {}
            for i, name in enumerate(sources):
                stem_tensor = estimates[i]
                if model_rate != source_rate:
                    import torchaudio

                    stem_tensor = torchaudio.functional.resample(
                        stem_tensor, model_rate, source_rate
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
                model=self._model,
            )
            self.progress.emit("Pronto!")
            self.finished.emit(stems, self._model)

        except Exception as e:
            self.error.emit(str(e))

    def _separate_demucs(self, waveform, source_rate: int):
        import torch
        import torchaudio
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        self.progress.emit("Carregando modelo Demucs...")
        model = get_model(self._model)
        model.eval()
        if source_rate != model.samplerate:
            waveform = torchaudio.functional.resample(
                waveform, source_rate, model.samplerate
            )

        self.progress.emit("Separando instrumentos... (pode levar alguns minutos)")
        with torch.no_grad():
            estimates = apply_model(
                model, waveform.unsqueeze(0), device="cpu", shifts=0, split=True
            )
        return model.sources, int(model.samplerate), estimates[0]

    def _separate_roformer(self, waveform, source_rate: int):
        import torch
        import torchaudio
        from services import roformer

        path = roformer.ensure_checkpoint(self.progress.emit)
        if source_rate != roformer.SAMPLE_RATE:
            waveform = torchaudio.functional.resample(
                waveform, source_rate, roformer.SAMPLE_RATE
            )

        def run(device):
            self.progress.emit("Carregando modelo de alta qualidade...")
            model = roformer.load_model(path, device)
            where = "GPU" if device.type == "cuda" else "CPU, pode demorar bastante"
            try:
                return roformer.demix(
                    model,
                    waveform,
                    device,
                    lambda done, total: self.progress.emit(
                        f"Separando em alta qualidade ({where})... {done}/{total}"
                    ),
                )
            finally:
                # Release VRAM right away; other apps may share the GPU.
                del model
                if device.type == "cuda":
                    torch.cuda.empty_cache()

        device = roformer.inference_device()
        try:
            estimates = run(device)
        except torch.cuda.OutOfMemoryError:
            if device.type != "cuda":
                raise
            self.progress.emit("Memória da GPU insuficiente; usando a CPU...")
            estimates = run(torch.device("cpu"))
        return roformer.SOURCES, roformer.SAMPLE_RATE, estimates

    def _load_cache(
        self,
        cache_dir: Path,
        source_rate: int,
        source_frames: int,
        source_channels: int,
        *,
        source_size: int | None = None,
        source_mtime_ns: int | None = None,
        names: list[str] = STEMS,
        model: str | None = None,
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
            for name in names:
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
                model=model,
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
        model: str | None = None,
    ):
        self._recover_cache_transaction(cache_dir)
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = self._staging_cache_path(cache_dir)
        backup = self._backup_cache_path(cache_dir)
        staging.mkdir(parents=True)

        names = next((names for names in STEM_SETS if set(names) == set(stems)), None)
        if names is None:
            raise InvalidStemCacheError(f"Conjunto de stems inesperado: {sorted(stems)}")

        try:
            for name in names:
                data = stems[name]
                if data.shape != (frame_count, channels):
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
            if model is not None:
                metadata["model"] = model
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
    finished = Signal(dict, str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _SepWorker | None = None

    @property
    def is_processing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def separate(
        self,
        file_path: str,
        song_id: str,
        model: str = DEFAULT_MODEL,
    ):
        """Load cached stems at least as good as ``model``, or run it."""
        if self.is_processing:
            return
        self._thread = QThread()
        self._worker = _SepWorker(file_path, song_id, model)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_finished(self, stems: dict, model: str):
        self._cleanup()
        self.finished.emit(stems, model)

    def _on_error(self, msg: str):
        self._cleanup()
        self.error.emit(msg)

    def _cleanup(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def has_cache(self, song_id: str, model: str = DEFAULT_MODEL) -> bool:
        """Whether cached stems at least as good as ``model`` exist."""
        cached = cached_model(CACHE_DIR / song_id)
        return cached is not None and MODEL_RANK[cached] >= MODEL_RANK[model]


def cached_stem_names(cache_dir: Path) -> list[str] | None:
    """Return the complete stem set stored in ``cache_dir``, newest first."""
    for names in STEM_SETS:
        if all((cache_dir / f"{name}.npy").exists() for name in names):
            return names
    return None


def cached_model(cache_dir: Path) -> str | None:
    """Return the model that produced the stems in ``cache_dir``, if complete."""
    names = cached_stem_names(cache_dir)
    if names is None:
        return None
    try:
        model = json.loads((cache_dir / "metadata.json").read_text()).get("model")
    except (OSError, ValueError, AttributeError):
        model = None
    if model in MODEL_RANK:
        return model
    # Caches written before the model was recorded came from Demucs.
    return "htdemucs" if names is LEGACY_STEMS else DEFAULT_MODEL
