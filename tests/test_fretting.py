from pathlib import Path
import sys
import unittest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from models.position_fix import PositionFix  # noqa: E402
from services import fretting  # noqa: E402
from services.note_detection_service import DetectedNote  # noqa: E402

E2, F2, A2, C3, D3, A3, B3, C4, CS4, D4, G4, GS4, A5, C6 = (
    40, 41, 45, 48, 50, 57, 59, 60, 61, 62, 67, 68, 81, 84
)


def note(onset, pitch, score=0.7, length=0.4):
    return DetectedNote(onset, onset + length, pitch, score)


def by_pitch(tab):
    return {t.pitch: t for t in tab}


class PositionTests(unittest.TestCase):
    def test_positions_cover_every_string_up_to_the_last_fret(self):
        self.assertEqual(
            fretting.positions(G4),
            [fretting.Position(1, 3), fretting.Position(2, 8),
             fretting.Position(3, 12), fretting.Position(4, 17)],
        )

    def test_low_e_has_one_position_and_high_notes_none(self):
        self.assertEqual(fretting.positions(E2), [fretting.Position(6, 0)])
        self.assertEqual(fretting.positions(C6), [fretting.Position(1, 20)])
        self.assertEqual(fretting.positions(C6 + 1), [])

    def test_string_names_follow_tab_order(self):
        self.assertEqual(fretting.string_names(), ["e", "B", "G", "D", "A", "E"])


class GroupingTests(unittest.TestCase):
    def test_a_strum_chains_close_onsets(self):
        events = fretting.group_events([note(1.0, C4), note(1.04, D4), note(1.08, G4)])
        self.assertEqual([len(e) for e in events], [3])

    def test_a_strum_never_grows_past_its_maximum_length(self):
        notes = [note(1.0 + 0.045 * i, p) for i, p in enumerate((C3, D3, A3, B3))]
        events = fretting.group_events(notes)
        self.assertGreater(len(events), 1)
        self.assertTrue(all(e[-1].onset - e[0].onset <= fretting.MAX_EVENT_LENGTH for e in events))

    def test_the_same_pitch_twice_in_a_strum_is_one_note(self):
        [event] = fretting.group_events([note(1.0, C4, 0.6, 0.07), note(1.03, C4, 0.5, 1.0)])
        self.assertEqual(len(event), 1)
        self.assertAlmostEqual(event[0].onset, 1.0)
        self.assertAlmostEqual(event[0].offset, 2.03)
        self.assertEqual(event[0].score, 0.6)

    def test_separate_attacks_of_the_same_note_stay_apart(self):
        events = fretting.group_events([note(1.0, C4), note(1.3, C4)])
        self.assertEqual(len(events), 2)


class AssignmentTests(unittest.TestCase):
    def test_minor_second_cluster_fits_one_hand_on_three_strings(self):
        tab = fretting.assign_positions([note(1.0, CS4), note(1.01, G4), note(1.02, GS4)])
        self.assertTrue(all(t.playable for t in tab))
        self.assertEqual(len({t.string for t in tab}), 3)
        frets = [t.fret for t in tab if t.fret > 0]
        self.assertLessEqual(max(frets) - min(frets), fretting.MAX_SPAN)

    def test_open_string_when_it_is_the_only_place(self):
        [t] = fretting.assign_positions([note(1.0, E2)])
        self.assertEqual((t.string, t.fret, t.playable), (6, 0, True))

    def test_hand_stays_in_its_position(self):
        # A3 fixed at the 7th fret; the line after it stays around there
        # instead of moving to the first frets or the open B string.
        notes = [note(1.0, A3)] + [note(1.5 + 0.5 * i, p) for i, p in enumerate((B3, C4, D4))]
        tab = fretting.assign_positions(notes, [PositionFix(A3, 1.0, 4)])
        self.assertEqual(by_pitch(tab)[A3].fret, 7)
        for t in tab[1:]:
            self.assertGreater(t.fret, 0, t)
            self.assertLessEqual(abs(t.fret - 7), fretting.MAX_SPAN, t)

    def test_a_ringing_string_is_not_cut(self):
        tab = fretting.assign_positions([note(1.0, C3, length=2.0), note(1.5, D3)])
        self.assertNotEqual(by_pitch(tab)[C3].string, by_pitch(tab)[D3].string)

    def test_out_of_range_note_is_flagged_and_the_rest_placed(self):
        tab = by_pitch(fretting.assign_positions([note(1.0, C4), note(1.0, C6 + 2)]))
        self.assertIsNone(tab[C6 + 2].string)
        self.assertFalse(tab[C6 + 2].playable)
        self.assertTrue(tab[C4].playable)

    def test_unplayable_chord_drops_its_weakest_note(self):
        # E2 and F2 both live only on the low E string.
        tab = by_pitch(fretting.assign_positions([note(1.0, E2, 0.8), note(1.01, F2, 0.4)]))
        self.assertTrue(tab[E2].playable)
        self.assertFalse(tab[F2].playable)
        self.assertEqual(tab[F2].string, 6)  # still shown, flagged

    def test_more_than_six_notes_keep_the_six_strongest(self):
        pitches = (E2, A2, D3, A3, C4, G4, A5)
        notes = [note(1.0 + 0.005 * i, p, score=0.9 - 0.05 * i) for i, p in enumerate(pitches)]
        tab = by_pitch(fretting.assign_positions(notes))
        self.assertFalse(tab[A5].playable)
        self.assertEqual(sum(t.playable for t in tab.values()), 6)

    def test_a_weak_high_harmonic_does_not_lift_the_chord(self):
        chord = [note(1.0, C3), note(1.01, G4, 0.6), note(1.02, A3), note(1.03, A5, 0.36)]
        tab = by_pitch(fretting.assign_positions(chord))
        self.assertFalse(tab[A5].playable)
        self.assertTrue(all(tab[p].fret <= fretting.HIGH_FRET for p in (C3, A3, G4)))

    def test_fixed_position_is_kept_and_marked(self):
        tab = by_pitch(fretting.assign_positions(
            [note(1.0, C4), note(1.01, G4)], [PositionFix(C4, 1.02, 5)]
        ))
        self.assertEqual((tab[C4].string, tab[C4].fret, tab[C4].fixed), (5, 15, True))
        self.assertFalse(tab[G4].fixed)
        self.assertNotEqual(tab[G4].string, 5)

    def test_conflicting_fixes_do_not_break_the_chord(self):
        fixes = [PositionFix(C4, 1.0, 3), PositionFix(D4, 1.01, 3)]
        tab = fretting.assign_positions([note(1.0, C4, 0.8), note(1.01, D4, 0.5)], fixes)
        self.assertEqual(sum(t.playable for t in tab), 1)
        self.assertTrue(all(t.fixed for t in tab))


class OrphanTests(unittest.TestCase):
    def test_orphans_are_fixes_without_a_note_or_a_valid_string(self):
        notes = [note(1.0, C4)]
        anchored = PositionFix(C4, 1.03, 2)
        missing = PositionFix(D4, 1.0, 2)
        wrong_string = PositionFix(C4, 1.0, 1)  # C4 is below the open high e
        self.assertEqual(
            fretting.orphan_fixes(notes, [anchored, missing, wrong_string]),
            [missing, wrong_string],
        )


if __name__ == "__main__":
    unittest.main()
