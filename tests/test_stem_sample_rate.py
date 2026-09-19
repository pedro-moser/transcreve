import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QCoreApplication

import services.separation_service as separation_service


FULL_STEM_DEPENDENCIES = all(
    importlib.util.find_spec(name) is not None for name in ("torch", "torchaudio")
)


@unittest.skipUnless(
    FULL_STEM_DEPENDENCIES,
    "requires the optional torch and torchaudio dependencies",
)
class SeparationSampleRateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_legacy_44100_cache_is_resampled_to_source_rate(self):
        source_rate = 48_000
        model_rate = 44_100
        duration_seconds = 0.1
        source_frames = int(source_rate * duration_seconds)
        model_frames = int(model_rate * duration_seconds)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.wav"
            t_source = np.arange(source_frames, dtype=np.float32) / source_rate
            source_audio = np.column_stack([
                np.sin(2 * np.pi * 440 * t_source),
                np.sin(2 * np.pi * 440 * t_source),
            ]).astype(np.float32)
            sf.write(source_path, source_audio, source_rate)

            cache_root = root / "stems"
            cache = cache_root / "song-id"
            cache.mkdir(parents=True)
            t_model = np.arange(model_frames, dtype=np.float32) / model_rate
            cached_stem = np.column_stack([
                np.sin(2 * np.pi * 440 * t_model),
                np.sin(2 * np.pi * 440 * t_model),
            ]).astype(np.float32)
            for name in separation_service.STEMS:
                np.save(cache / f"{name}.npy", cached_stem)

            results = []
            errors = []
            with patch.object(separation_service, "CACHE_DIR", cache_root):
                worker = separation_service._SepWorker(str(source_path), "song-id")
                worker.finished.connect(results.append)
                worker.error.connect(errors.append)
                worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
            for stem in results[0].values():
                self.assertEqual(stem.shape, (source_frames, 2))

            metadata = json.loads((cache / "metadata.json").read_text())
            self.assertEqual(metadata["sample_rate"], source_rate)
            self.assertEqual(metadata["frame_count"], source_frames)

            spectrum = np.fft.rfft(results[0]["other"][:, 0])
            peak_hz = np.fft.rfftfreq(source_frames, 1 / source_rate)[np.argmax(np.abs(spectrum))]
            self.assertAlmostEqual(peak_hz, 440, delta=15)
    def test_mixed_or_stale_cache_is_rejected_without_overwrite(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "song-id"
            cache.mkdir()
            expected_shapes = {}
            for index, name in enumerate(separation_service.STEMS):
                frames = 4_800 if index == 1 else 4_410
                stem = np.zeros((frames, 2), dtype=np.float32)
                np.save(cache / f"{name}.npy", stem)
                expected_shapes[name] = stem.shape
            (cache / "metadata.json").write_text(json.dumps({
                "version": 2,
                "sample_rate": 48_000,
                "frame_count": 4_800,
            }))

            worker = separation_service._SepWorker("unused.wav", "song-id")
            with self.assertRaises(separation_service.InvalidStemCacheError):
                worker._load_cache(cache, 48_000, 4_800, 2)

            persisted_shapes = {
                name: np.load(cache / f"{name}.npy", mmap_mode="r").shape
                for name in separation_service.STEMS
            }
            self.assertEqual(persisted_shapes, expected_shapes)

    def test_cache_publish_is_atomic_and_recoverable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "song-id"
            cache.mkdir()
            original = np.ones((100, 2), dtype=np.float32)
            for name in separation_service.STEMS:
                np.save(cache / f"{name}.npy", original)

            worker = separation_service._SepWorker("unused.wav", "song-id")
            replacement = {
                name: np.full((120, 2), index, dtype=np.float32)
                for index, name in enumerate(separation_service.STEMS)
            }
            worker._save_cache(cache, replacement, 48_000, 120, 2)

            self.assertFalse(worker._staging_cache_path(cache).exists())
            self.assertFalse(worker._backup_cache_path(cache).exists())
            metadata = json.loads((cache / "metadata.json").read_text())
            self.assertEqual(metadata["channels"], 2)
            for name, expected in replacement.items():
                np.testing.assert_array_equal(np.load(cache / f"{name}.npy"), expected)

            backup = worker._backup_cache_path(cache)
            staging = worker._staging_cache_path(cache)
            cache.replace(backup)
            staging.mkdir()
            (staging / "partial").write_text("incomplete")
            worker._recover_cache_transaction(cache)

            self.assertTrue(cache.exists())
            self.assertFalse(backup.exists())
            self.assertFalse(staging.exists())
            for name, expected in replacement.items():
                np.testing.assert_array_equal(np.load(cache / f"{name}.npy"), expected)

    def test_mono_channel_count_is_preserved(self):
        stereo = np.column_stack([
            np.ones(64, dtype=np.float32),
            np.zeros(64, dtype=np.float32),
        ])
        mono = separation_service._SepWorker._fit_channel_count(stereo, 1)
        self.assertEqual(mono.shape, (64, 1))
        np.testing.assert_allclose(mono[:, 0], 0.5)

    def test_malformed_v3_source_identity_is_rejected_as_invalid_cache(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "song-id"
            cache.mkdir()
            stems = {
                name: np.zeros((120, 2), dtype=np.float32)
                for name in separation_service.STEMS
            }
            for name, stem in stems.items():
                np.save(cache / f"{name}.npy", stem)
            (cache / "metadata.json").write_text(json.dumps({
                "version": 3,
                "sample_rate": 48_000,
                "frame_count": 120,
                "channels": 2,
                "source_size": "not-a-number",
                "source_mtime_ns": 2_000,
            }))

            worker = separation_service._SepWorker("unused.wav", "song-id")
            with self.assertRaises(separation_service.InvalidStemCacheError):
                worker._load_cache(
                    cache,
                    48_000,
                    120,
                    2,
                    source_size=1_000,
                    source_mtime_ns=2_000,
                )

    def test_source_identity_change_invalidates_v3_cache(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "song-id"
            worker = separation_service._SepWorker("unused.wav", "song-id")
            stems = {
                name: np.zeros((120, 2), dtype=np.float32)
                for name in separation_service.STEMS
            }
            worker._save_cache(
                cache,
                stems,
                48_000,
                120,
                2,
                source_size=1_000,
                source_mtime_ns=2_000,
            )

            with self.assertRaises(separation_service.InvalidStemCacheError):
                worker._load_cache(
                    cache,
                    48_000,
                    120,
                    2,
                    source_size=1_001,
                    source_mtime_ns=2_000,
                )


if __name__ == "__main__":
    unittest.main()
