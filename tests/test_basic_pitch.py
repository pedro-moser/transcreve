import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services import basic_pitch as bp  # noqa: E402

HAS_ONNXRUNTIME = importlib.util.find_spec("onnxruntime") is not None


def activations(frames: int) -> bp.Activations:
    return bp.Activations(
        note=np.zeros((frames, bp.N_PITCHES), np.float32),
        onset=np.zeros((frames, bp.N_PITCHES), np.float32),
        contour=np.zeros((frames, 3 * bp.N_PITCHES), np.float32),
        times=bp.frame_times(frames),
    )


def sound(act: bp.Activations, pitch: int, start: int, end: int, level: float = 0.8):
    act.note[start:end, pitch - bp.MIDI_OFFSET] = level
    act.onset[start, pitch - bp.MIDI_OFFSET] = 0.9


class FrameGridTests(unittest.TestCase):
    def test_frames_are_one_hop_apart_inside_a_window(self):
        times = bp.frame_times(3 * bp.FRAMES_PER_STEP)
        steps = np.diff(times[: bp.FRAMES_PER_STEP])
        np.testing.assert_allclose(steps, bp.FFT_HOP / bp.SAMPLE_RATE)
        self.assertAlmostEqual(times[bp.FRAMES_PER_STEP], bp.WINDOW_STEP / bp.SAMPLE_RATE)
        self.assertTrue(np.all(np.diff(times) > 0))

    def test_frames_cover_the_whole_audio(self):
        hop = bp.FFT_HOP / bp.SAMPLE_RATE
        for seconds in (0.5, 2.0, 30.0, 300.0):
            samples = int(seconds * bp.SAMPLE_RATE)
            last = bp.frame_times(bp._frames_covering(samples))[-1]
            self.assertLess(last, seconds)
            self.assertGreaterEqual(last, seconds - hop - 1e-9)


class DecoderTests(unittest.TestCase):
    def test_note_times_come_from_the_frame_grid(self):
        act = activations(400)
        sound(act, 57, 200, 260)
        (note,) = bp.extract_notes(act)
        self.assertEqual(note.pitch, 57)
        self.assertAlmostEqual(note.onset, act.times[200])
        self.assertAlmostEqual(note.score, 0.8, places=5)

    def test_neighbor_suppression_drops_the_lower_of_a_minor_second(self):
        act = activations(200)
        sound(act, 59, 50, 120)
        sound(act, 60, 50, 120)

        with_suppression = sorted(n.pitch for n in bp.extract_notes(act))
        without = sorted(n.pitch for n in bp.extract_notes(act, neighbor_suppression=False))

        self.assertEqual(with_suppression, [60])
        self.assertEqual(without, [59, 60])

    def test_minimum_length_is_exclusive(self):
        act = activations(200)
        sound(act, 64, 20, 31)  # 11 frames: dropped with the default
        sound(act, 67, 20, 32)  # 12 frames: kept
        pitches = [n.pitch for n in bp.extract_notes(act, melodia=False)]
        self.assertEqual(pitches, [67])

    def test_pitch_range_is_inclusive(self):
        act = activations(200)
        for pitch in (39, 40, 88, 89):
            sound(act, pitch, 20, 60)
        notes = bp.extract_notes(act, min_pitch=40, max_pitch=88)
        self.assertEqual(sorted(n.pitch for n in notes), [40, 88])

    def test_silence_decodes_to_no_notes(self):
        self.assertEqual(bp.extract_notes(activations(100)), [])


class ModelFileTests(unittest.TestCase):
    def test_vendored_model_matches_checksum(self):
        digest = hashlib.sha256(Path(bp.MODEL_PATH).read_bytes()).hexdigest()
        self.assertEqual(digest, bp.MODEL_SHA256)


@unittest.skipUnless(HAS_ONNXRUNTIME, "onnxruntime não instalado")
class InferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from validation.sintese import corda

        cls.session = bp.load_session()
        cls.corda = staticmethod(corda)

    def render(self, seconds: float, notes: list[tuple[float, int]], sr: int = 22_050):
        rng = np.random.default_rng(0)
        audio = np.zeros(int(seconds * sr), np.float32)
        for onset, pitch in notes:
            tone = self.corda(pitch, min(1.0, seconds - onset), sr, rng)
            start = int(onset * sr)
            audio[start : start + len(tone)] += tone
        return audio

    # With a single loud note, upstream's inferred onsets are rescaled to the
    # note's own peak and flatten it into a plateau that argrelmax rejects;
    # the note then only comes from the melodia pass, ~25 ms early. Timing is
    # checked without that step.
    def test_plucked_note_is_found_on_time(self):
        audio = self.render(4.0, [(1.0, 57)])
        notes = bp.extract_notes(bp.infer(audio, 22_050, self.session), infer_onsets=False)
        found = [n for n in notes if n.pitch == 57]
        self.assertEqual(len(found), 1)
        self.assertLess(abs(found[0].onset - 1.0), 0.02)

    def test_resampled_input_keeps_timing(self):
        audio = self.render(4.0, [(2.0, 64)], sr=44_100)
        notes = bp.extract_notes(bp.infer(audio, 44_100, self.session), infer_onsets=False)
        self.assertTrue(any(n.pitch == 64 and abs(n.onset - 2.0) < 0.02 for n in notes))

    def test_notes_at_the_end_of_a_long_song_are_transcribed(self):
        # Upstream drops the last ~0.7 % of the audio: 2 s of 5 minutes.
        audio = self.render(300.0, [(10.0, 57), (298.8, 60)])
        act = bp.infer(audio, 22_050, self.session)
        notes = bp.extract_notes(act, infer_onsets=False)
        self.assertTrue(any(n.pitch == 60 and abs(n.onset - 298.8) < 0.02 for n in notes))
        self.assertTrue(any(n.pitch == 57 and abs(n.onset - 10.0) < 0.02 for n in notes))


if __name__ == "__main__":
    unittest.main()
