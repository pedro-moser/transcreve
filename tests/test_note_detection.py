import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services import note_detection_service as nd  # noqa: E402

HAS_ONNXRUNTIME = importlib.util.find_spec("onnxruntime") is not None
SONG_ID = "song-1"


def render(seconds: float, notes: list[tuple[float, float]], sr: int) -> np.ndarray:
    """Plucked strings; pitches may be fractional (MIDI + cents / 100)."""
    from validation.sintese import corda

    rng = np.random.default_rng(0)
    audio = np.zeros(int(seconds * sr), np.float32)
    for onset, pitch in notes:
        tone = corda(pitch, min(1.0, seconds - onset), sr, rng)
        start = int(onset * sr)
        audio[start : start + len(tone)] += tone
    return audio


class TempDirsTestCase(unittest.TestCase):
    """Points the stem and analysis caches at a temporary directory."""

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.stems_dir = root / "stems"
        self.analysis_dir = root / "analysis"
        for name, value in (("STEMS_CACHE_DIR", self.stems_dir), ("CACHE_DIR", self.analysis_dir)):
            patcher = patch.object(nd, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def write_stems(self, song_id=SONG_ID, names=("guitar",), audio=None, rate=44_100,
                    metadata=True):
        cache = self.stems_dir / song_id
        cache.mkdir(parents=True, exist_ok=True)
        if audio is None:
            audio = np.zeros((rate, 2), np.float32)
        for name in names:
            np.save(cache / f"{name}.npy", audio)
        if metadata:
            (cache / "metadata.json").write_text(
                json.dumps({"version": 3, "sample_rate": rate, "frame_count": len(audio)})
            )


class StemAvailabilityTests(TempDirsTestCase):
    def test_guitar_stem_with_rate_metadata_is_available(self):
        self.write_stems()
        self.assertEqual(nd.note_stems(SONG_ID), ["guitar"])
        self.assertEqual(nd.stem_sample_rate(SONG_ID), 44_100)

    def test_six_stem_cache_offers_every_instrument_but_vocals_and_drums(self):
        self.write_stems(names=("vocals", "drums", "bass", "guitar", "piano", "other"))
        self.assertEqual(nd.note_stems(SONG_ID), ["guitar", "bass", "piano", "other"])

    def test_four_stem_cache_offers_bass_and_other(self):
        self.write_stems(names=("vocals", "drums", "bass", "other"))
        self.assertEqual(nd.note_stems(SONG_ID), ["bass", "other"])

    def test_cache_without_rate_metadata_is_not_used(self):
        self.write_stems(metadata=False)
        self.assertEqual(nd.note_stems(SONG_ID), [])

    def test_missing_song_has_no_stems(self):
        self.assertEqual(nd.note_stems("other-song"), [])

    def test_each_stem_decodes_its_own_range(self):
        self.assertEqual(nd.extraction("guitar"), nd.EXTRACTION)
        bass = nd.extraction("bass")
        self.assertEqual((bass["min_pitch"], bass["max_pitch"]), (28, 67))
        self.assertEqual(bass["min_frames"], nd.EXTRACTION["min_frames"])
        piano = nd.extraction("piano")
        self.assertEqual((piano["min_pitch"], piano["max_pitch"]), (21, 108))


class NotesCacheTests(TempDirsTestCase):
    NOTES = [nd.DetectedNote(1.0, 1.5, 57, 0.7), nd.DetectedNote(1.01, 2.0, 58, 0.42)]

    def setUp(self):
        super().setUp()
        self.write_stems(names=("guitar", "bass"))

    def test_cached_notes_round_trip(self):
        key = nd.cache_key(SONG_ID, "guitar")
        nd.save_cached_notes(SONG_ID, "guitar", key, 3.0, self.NOTES)
        self.assertEqual(
            nd.load_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar")), self.NOTES
        )

    def test_guitar_notes_detected_before_other_stems_stay_cached(self):
        # The cache of the guitar-only version: notes.json, keyed on EXTRACTION.
        stat = nd.stem_path(SONG_ID, "guitar").stat()
        key = {
            "version": nd.CACHE_VERSION,
            "stem": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
            "model_sha256": nd.bp.MODEL_SHA256,
            "extraction": dict(nd.EXTRACTION),
            "tuning_gate_cents": nd.TUNING_GATE_CENTS,
        }
        nd.save_cached_notes(SONG_ID, "guitar", key, 0.0, self.NOTES)
        self.assertTrue((self.analysis_dir / SONG_ID / "notes.json").is_file())
        self.assertEqual(
            nd.load_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar")), self.NOTES
        )

    def test_each_stem_has_its_own_cache(self):
        nd.save_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar"), 0.0, self.NOTES)
        self.assertIsNone(nd.load_cached_notes(SONG_ID, "bass", nd.cache_key(SONG_ID, "bass")))
        bass_notes = self.NOTES[:1]
        nd.save_cached_notes(SONG_ID, "bass", nd.cache_key(SONG_ID, "bass"), 0.0, bass_notes)
        self.assertEqual(
            nd.load_cached_notes(SONG_ID, "bass", nd.cache_key(SONG_ID, "bass")), bass_notes
        )
        self.assertEqual(
            nd.load_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar")), self.NOTES
        )

    def test_new_guitar_stem_makes_cached_notes_stale(self):
        nd.save_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar"), 0.0, self.NOTES)
        stem = nd.stem_path(SONG_ID, "guitar")
        before = stem.stat().st_mtime_ns
        self.write_stems()
        os.utime(stem, ns=(before + 1_000_000, before + 1_000_000))
        self.assertIsNone(
            nd.load_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar"))
        )

    def test_new_extraction_parameters_make_cached_notes_stale(self):
        for stem in ("guitar", "bass"):
            nd.save_cached_notes(SONG_ID, stem, nd.cache_key(SONG_ID, stem), 0.0, self.NOTES)
        with patch.dict(nd.EXTRACTION, {"min_frames": 11}):
            for stem in ("guitar", "bass"):
                self.assertIsNone(
                    nd.load_cached_notes(SONG_ID, stem, nd.cache_key(SONG_ID, stem)), stem
                )

    def test_unreadable_cache_is_a_miss(self):
        path = self.analysis_dir / SONG_ID / "notes.json"
        path.parent.mkdir(parents=True)
        path.write_text("{")
        self.assertIsNone(
            nd.load_cached_notes(SONG_ID, "guitar", nd.cache_key(SONG_ID, "guitar"))
        )


@unittest.skipUnless(HAS_ONNXRUNTIME, "onnxruntime não instalado")
class DetectionTests(TempDirsTestCase):
    @classmethod
    def setUpClass(cls):
        from services import basic_pitch as bp

        cls.session = bp.load_session()

    def test_simultaneous_minor_second_keeps_both_notes(self):
        # B3 C4 D4 strummed; upstream's decoder drops the B3.
        audio = render(3.0, [(1.0, 59), (1.015, 60), (1.03, 62)], 22_050)
        notes, _ = nd.detect_notes(audio, 22_050, self.session)
        found = {n.pitch for n in notes if abs(n.onset - 1.0) < 0.06}
        self.assertTrue({59, 60, 62} <= found, found)

    def test_bass_range_reaches_below_the_guitar(self):
        # A1 sits below the guitar's low E: only the bass decodes it.
        audio = render(3.0, [(1.0, 33)], 22_050)
        bass, _ = nd.detect_notes(audio, 22_050, self.session, "bass")
        guitar, _ = nd.detect_notes(audio, 22_050, self.session, "guitar")
        self.assertIn(33, {n.pitch for n in bass if abs(n.onset - 1.0) < 0.06})
        self.assertNotIn(33, {n.pitch for n in guitar})

    def test_sharp_recording_is_retuned_in_song_time(self):
        # 40 cents sharp: the model input is slowed down to reach A440, so
        # uncorrected times would land 2.3 % late (70 ms at 3 s).
        sr = 44_100
        audio = render(5.0, [(1.0, 57.4), (3.0, 64.4)], sr)
        notes, cents = nd.detect_notes(audio, sr, self.session)
        self.assertAlmostEqual(cents, 40, delta=10)
        for onset, pitch in ((1.0, 57), (3.0, 64)):
            matches = [n for n in notes if n.pitch == pitch]
            self.assertTrue(matches, f"pitch {pitch} not found in {notes}")
            self.assertLess(min(abs(n.onset - onset) for n in matches), 0.03)

    def test_worker_detects_once_and_then_reads_the_cache(self):
        sr = 44_100
        mono = render(3.0, [(1.0, 57)], sr)
        self.write_stems(audio=np.stack([mono, mono], axis=1), rate=sr)

        def run_worker():
            results = []
            worker = nd._DetectWorker(SONG_ID, "guitar")
            worker.finished.connect(
                lambda song_id, stem, notes: results.append((song_id, stem, notes))
            )
            worker.error.connect(lambda song_id, stem, msg: self.fail(msg))
            worker.run()
            return [(song_id, notes) for song_id, stem, notes in results if stem == "guitar"]

        [(song_id, notes)] = run_worker()
        self.assertEqual(song_id, SONG_ID)
        self.assertTrue(any(n.pitch == 57 for n in notes))

        with patch.object(nd, "detect_notes", side_effect=AssertionError("not cached")):
            [(_, cached)] = run_worker()
        self.assertEqual([n.pitch for n in cached], [n.pitch for n in notes])
        for got, expected in zip(cached, notes):
            self.assertAlmostEqual(got.onset, expected.onset, places=3)


class AvailabilityTests(unittest.TestCase):
    def test_unavailable_without_onnxruntime(self):
        with patch.object(nd.importlib.util, "find_spec", return_value=None):
            self.assertFalse(nd.is_available())

    def test_unavailable_without_model_file(self):
        with patch.object(nd.bp, "MODEL_PATH", Path("/nonexistent/model.onnx")):
            self.assertFalse(nd.is_available())


if __name__ == "__main__":
    unittest.main()
