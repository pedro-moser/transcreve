from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services import fretting, tunings  # noqa: E402


class TuningTests(unittest.TestCase):
    def test_standard_tunings_are_the_tabs_defaults(self):
        self.assertEqual(tunings.default(tunings.GUITAR), fretting.STANDARD_TUNING)
        self.assertEqual(tunings.default(tunings.BASS), fretting.BASS_TUNING)

    def test_note_names_become_open_pitches_from_the_high_string(self):
        guitar = tunings.TUNINGS[tunings.GUITAR]
        self.assertEqual(guitar[7][0].strings, (64, 59, 55, 50, 45, 40, 35))
        self.assertEqual(guitar[8][0].strings, (64, 59, 55, 50, 45, 40, 35, 30))
        self.assertEqual(guitar[6][1].strings, (63, 58, 54, 49, 44, 39))  # Eb
        self.assertEqual(tunings.TUNINGS[tunings.BASS][6][0].strings, (48, 43, 38, 33, 28, 23))

    def test_each_tuning_has_the_strings_of_its_count_from_high_to_low(self):
        for instrument, by_count in tunings.TUNINGS.items():
            for count, presets in by_count.items():
                for tuning in presets:
                    self.assertEqual(len(tuning.strings), count, tuning)
                    self.assertEqual(list(tuning.strings), sorted(tuning.strings, reverse=True), tuning)
                names = [t.name for t in presets]
                self.assertEqual(len(names), len(set(names)), (instrument, count))

    def test_unknown_tuning_is_named_by_its_notes(self):
        self.assertEqual(tunings.name(tunings.GUITAR, fretting.STANDARD_TUNING), "E padrão")
        self.assertEqual(
            tunings.name(tunings.GUITAR, (64, 60, 55, 48, 43, 36)), "C G C G C E"  # open C
        )
        self.assertEqual(tunings.name(tunings.GUITAR, (62, 57, 55, 50, 45, 38)), "DADGAD")
        self.assertEqual(tunings.name(tunings.GUITAR, (64,) * 9), "E E E E E E E E E")


if __name__ == "__main__":
    unittest.main()
