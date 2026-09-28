import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication

import services.separation_service as separation_service


FULL_STEM_DEPENDENCIES = all(
    importlib.util.find_spec(name) is not None
    for name in ("torch", "torchaudio", "einops")
)


def _stems(names, frames=120):
    return {name: np.zeros((frames, 2), dtype=np.float32) for name in names}


class CachedModelTests(unittest.TestCase):
    def test_model_is_recorded_and_inferred_for_old_caches(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = separation_service._SepWorker("unused.wav", "song-id")

            recorded = root / "recorded"
            worker._save_cache(
                recorded, _stems(separation_service.STEMS), 48_000, 120, 2,
                model=separation_service.HQ_MODEL,
            )
            self.assertEqual(
                separation_service.cached_model(recorded), separation_service.HQ_MODEL
            )

            old_six = root / "old-six"
            worker._save_cache(old_six, _stems(separation_service.STEMS), 48_000, 120, 2)
            self.assertEqual(
                separation_service.cached_model(old_six), separation_service.DEFAULT_MODEL
            )

            old_four = root / "old-four"
            worker._save_cache(
                old_four, _stems(separation_service.LEGACY_STEMS), 48_000, 120, 2
            )
            self.assertEqual(separation_service.cached_model(old_four), "htdemucs")
            self.assertIsNone(separation_service.cached_model(root / "missing"))

    def test_has_cache_accepts_equal_or_better_models_only(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = separation_service._SepWorker("unused.wav", "song-id")
            worker._save_cache(
                root / "song-id", _stems(separation_service.STEMS), 48_000, 120, 2,
                model=separation_service.DEFAULT_MODEL,
            )
            with patch.object(separation_service, "CACHE_DIR", root):
                service = separation_service.SeparationService()
                self.assertTrue(
                    service.has_cache("song-id", separation_service.DEFAULT_MODEL)
                )
                self.assertFalse(service.has_cache("song-id", separation_service.HQ_MODEL))

    def test_rewritten_legacy_cache_keeps_its_model(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "song-id"
            worker = separation_service._SepWorker("unused.wav", "song-id")
            worker._save_cache(
                cache, _stems(separation_service.STEMS), 48_000, 120, 2,
                model=separation_service.HQ_MODEL,
            )
            # Mono source forces a rewrite of the cached stems.
            worker._load_cache(
                cache, 48_000, 120, 1, model=separation_service.HQ_MODEL
            )
            metadata = json.loads((cache / "metadata.json").read_text())
            self.assertEqual(metadata["model"], separation_service.HQ_MODEL)
            self.assertEqual(metadata["channels"], 1)


@unittest.skipUnless(
    FULL_STEM_DEPENDENCIES,
    "requires the optional torch, torchaudio and einops dependencies",
)
class ModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _run_worker(self, root: Path, model: str):
        import torch

        source_path = root / "source.wav"
        if not source_path.exists():
            sf.write(source_path, np.zeros((4_800, 2), dtype=np.float32), 48_000)

        calls = []

        def fake_roformer(worker, waveform, source_rate):
            calls.append(model)
            frames = waveform.shape[-1]
            return (
                ["bass", "drums", "other", "vocals", "guitar", "piano"],
                source_rate,
                torch.zeros((6, 2, frames)),
            )

        results, errors = [], []
        with (
            patch.object(separation_service, "CACHE_DIR", root / "stems"),
            patch.object(
                separation_service._SepWorker, "_separate_roformer", fake_roformer
            ),
        ):
            worker = separation_service._SepWorker(str(source_path), "song-id", model)
            worker.finished.connect(lambda stems, used: results.append(used))
            worker.error.connect(errors.append)
            worker.run()
        self.assertEqual(errors, [])
        return results[0], calls

    def test_better_cache_is_reused_and_worse_cache_is_replaced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.wav").parent.mkdir(exist_ok=True)
            sf.write(root / "source.wav", np.zeros((4_800, 2), dtype=np.float32), 48_000)
            stat = (root / "source.wav").stat()
            separation_service._SepWorker("unused.wav", "song-id")._save_cache(
                root / "stems" / "song-id",
                _stems(separation_service.STEMS, 4_800),
                48_000, 4_800, 2,
                source_size=stat.st_size,
                source_mtime_ns=stat.st_mtime_ns,
                model=separation_service.DEFAULT_MODEL,
            )

            used, calls = self._run_worker(root, separation_service.HQ_MODEL)
            self.assertEqual(used, separation_service.HQ_MODEL)
            self.assertEqual(calls, [separation_service.HQ_MODEL])

            # The high-quality cache now satisfies a "Padrão" request too.
            used, calls = self._run_worker(root, separation_service.DEFAULT_MODEL)
            self.assertEqual(used, separation_service.HQ_MODEL)
            self.assertEqual(calls, [])


@unittest.skipUnless(
    FULL_STEM_DEPENDENCIES,
    "requires the optional torch, torchaudio and einops dependencies",
)
class RoformerTests(unittest.TestCase):
    def test_chunks_cover_the_track_without_repeating_the_tail(self):
        from services import roformer

        self.assertEqual(roformer.chunk_starts(1_000), [0])
        starts = roformer.chunk_starts(roformer.CHUNK_SIZE * 3 + 17)
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1] + roformer.CHUNK_SIZE, roformer.CHUNK_SIZE * 3 + 17)
        self.assertEqual(len(starts), len(set(starts)))
        self.assertTrue(all(b - a <= roformer.CHUNK_STEP for a, b in zip(starts, starts[1:])))

    def test_demix_blends_chunks_back_to_the_input(self):
        import torch
        from services import roformer

        class PassThrough(torch.nn.Module):
            num_stems = 2

            def forward(self, audio):
                return torch.stack([audio * 0.25, audio * 0.75], dim=1)

        length = roformer.CHUNK_SIZE + roformer.CHUNK_STEP + 1_234
        mix = torch.randn(2, length)
        estimates = roformer.demix(PassThrough(), mix, torch.device("cpu"))
        self.assertEqual(tuple(estimates.shape), (2, 2, length))
        torch.testing.assert_close(estimates.sum(0), mix, atol=1e-5, rtol=1e-5)

    def test_small_model_preserves_length_and_stem_layout(self):
        import torch
        from services import roformer

        model = roformer.BSRoformer(
            dim=16,
            depth=1,
            num_stems=3,
            time_transformer_depth=1,
            freq_transformer_depth=1,
            dim_head=8,
            heads=2,
            mask_estimator_depth=2,
            mlp_expansion_factor=2,
        ).eval()
        audio = torch.randn(1, 2, 5_000)  # not a multiple of the STFT hop
        with torch.inference_mode():
            output = model(audio)
        self.assertEqual(tuple(output.shape), (1, 3, 2, 5_000))
        self.assertTrue(torch.isfinite(output).all())


if __name__ == "__main__":
    unittest.main()
