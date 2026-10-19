from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import app_settings  # noqa: E402
from models.position_fix import PositionFix  # noqa: E402
from models.song import Song  # noqa: E402
from screens import player_screen  # noqa: E402
from services import fretting  # noqa: E402
from services import note_detection_service as nd  # noqa: E402
from services.note_detection_service import DetectedNote  # noqa: E402
from services.storage_service import StorageService  # noqa: E402
from widgets.tab_widget import TabWidget  # noqa: E402

B1, C4, G4, GS4 = 35, 60, 67, 68
STANDARD = fretting.STANDARD_TUNING
SEVEN = STANDARD + (B1,)
EIGHT = SEVEN + (30,)
DROP_D = STANDARD[:5] + (38,)
NOTES = [
    DetectedNote(1.0, 2.0, C4, 0.7),
    DetectedNote(1.01, 2.0, G4, 0.6),
    DetectedNote(3.0, 3.5, GS4, 0.65),
]


class PositionFixStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.storage = StorageService(Path(self.temp_dir.name) / "test.db")

    def tearDown(self):
        self.storage.close()
        self.temp_dir.cleanup()

    def test_fixes_round_trip_and_replace(self):
        fixes = [PositionFix(C4, 1.0, 3), PositionFix(G4, 1.01, 2)]
        self.storage.set_position_fixes("song", "guitar", fixes)
        self.assertEqual(self.storage.get_position_fixes("song", "guitar"), fixes)
        self.storage.set_position_fixes("song", "guitar", fixes[:1])
        self.assertEqual(self.storage.get_position_fixes("song", "guitar"), fixes[:1])
        self.assertEqual(self.storage.get_position_fixes("other", "guitar"), [])

    def test_each_stem_keeps_its_own_fixes(self):
        guitar = [PositionFix(C4, 1.0, 3)]
        other = [PositionFix(C4, 1.0, 5)]  # the same note, bleeding into "other"
        self.storage.set_position_fixes("song", "guitar", guitar)
        self.storage.set_position_fixes("song", "other", other)
        self.assertEqual(self.storage.get_position_fixes("song", "guitar"), guitar)
        self.assertEqual(self.storage.get_position_fixes("song", "other"), other)
        self.assertEqual(self.storage.get_position_fixes("song", "bass"), [])
        self.storage.set_position_fixes("song", "other", [])
        self.assertEqual(self.storage.get_position_fixes("song", "guitar"), guitar)

    def test_guitar_fixes_saved_before_other_stems_are_kept(self):
        self.storage._conn.execute(
            """INSERT INTO note_edits (song_id, kind, pitch, onset_ms, data)
               VALUES ('song', 'posicao', ?, 1000, '{"string": 3}')""",
            (C4,),
        )
        self.assertEqual(
            self.storage.get_position_fixes("song", "guitar"), [PositionFix(C4, 1.0, 3)]
        )

    def test_deleting_a_song_deletes_its_fixes_and_tunings(self):
        song = Song(title="Teste", file_path="/x.wav")
        self.storage.save_song(song)
        self.storage.set_position_fixes(song.id, "guitar", [PositionFix(C4, 1.0, 3)])
        self.storage.set_position_fixes(song.id, "bass", [PositionFix(40, 1.0, 4)])
        self.storage.set_tuning(song.id, "guitar", SEVEN)
        self.storage.delete_song(song.id)
        self.assertEqual(self.storage.get_position_fixes(song.id, "guitar"), [])
        self.assertEqual(self.storage.get_position_fixes(song.id, "bass"), [])
        self.assertIsNone(self.storage.get_tuning(song.id, "guitar"))

    def test_tuning_round_trips_per_song_and_instrument(self):
        self.assertIsNone(self.storage.get_tuning("song", "guitar"))
        self.storage.set_tuning("song", "guitar", SEVEN)
        self.storage.set_tuning("song", "bass", fretting.BASS_TUNING)
        self.storage.set_tuning("song", "guitar", EIGHT)
        self.assertEqual(self.storage.get_tuning("song", "guitar"), EIGHT)
        self.assertEqual(self.storage.get_tuning("song", "bass"), fretting.BASS_TUNING)
        self.assertIsNone(self.storage.get_tuning("another-song", "guitar"))


class TabWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = TabWidget()
        self.tab.resize(800, 240)
        self.tab.set_duration(60_000)
        self.tab.set_notes(fretting.assign_positions(NOTES))

    def tearDown(self):
        self.tab.deleteLater()

    def test_note_at_finds_a_number_on_its_string(self):
        target = next(t for t in self.tab.notes if t.pitch == G4)
        self.assertEqual(self.tab.note_at(1500, target.string), target)
        self.assertIsNone(self.tab.note_at(2500, target.string))
        self.assertIsNone(self.tab.note_at(1500, 0))

    def test_alternatives_are_every_place_for_the_pitch(self):
        target = next(t for t in self.tab.notes if t.pitch == G4)
        self.assertEqual(self.tab.alternatives(target), fretting.positions(G4))

    def test_clicking_a_number_offers_its_positions(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest

        self.tab.show()
        self.app.processEvents()
        target = next(t for t in self.tab.notes if t.pitch == G4)
        scene = self.tab.getViewBox().mapViewToScene(QPointF(target.onset * 1000, target.string))
        offered, chosen = [], []
        self.tab.position_chosen.connect(lambda note, string: chosen.append((note.pitch, string)))

        def pick(menu, *args):
            offered.extend(a.data() for a in menu.actions() if a.data() is not None)
            return next(a for a in menu.actions() if a.data() == 3)

        with patch.object(self.tab, "_exec_menu", pick):
            QTest.mouseClick(self.tab.viewport(), Qt.LeftButton, pos=self.tab.mapFromScene(scene))
        self.assertEqual(offered, [p.string for p in fretting.positions(G4)])
        self.assertEqual(chosen, [(G4, 3)])

    def test_painting_draws_without_crashing(self):
        self.tab.show()
        self.assertFalse(self.tab.grab().isNull())

    def test_bass_tuning_draws_four_strings(self):
        E1, A2 = 28, 45
        self.tab.set_tuning(fretting.BASS_TUNING)
        self.assertEqual(self.tab.notes, [])
        self.assertEqual(self.tab.getPlotItem().getAxis("left").names, ["G", "D", "A", "E"])
        self.assertEqual(len(self.tab._string_lines), 4)
        notes = [DetectedNote(1.0, 2.0, E1, 0.7), DetectedNote(3.0, 3.5, A2, 0.7)]
        self.tab.set_notes(fretting.assign_positions(notes, tuning=fretting.BASS_TUNING))
        low = next(t for t in self.tab.notes if t.pitch == E1)
        self.assertEqual((low.string, low.fret), (4, 0))
        self.assertEqual(self.tab.note_at(1500, 4), low)
        self.assertIsNone(self.tab.note_at(1500, 5))
        high = next(t for t in self.tab.notes if t.pitch == A2)
        self.assertEqual(
            self.tab.alternatives(high), fretting.positions(A2, fretting.BASS_TUNING)
        )
        self.tab.show()
        self.assertFalse(self.tab.grab().isNull())


class PlayerTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name)
        stems = root / "stems"
        for target, name, value in (
            (nd, "STEMS_CACHE_DIR", stems),
            (nd, "CACHE_DIR", root / "analysis"),
            (app_settings, "_SETTINGS_PATH", root / "settings.json"),
            (player_screen, "notes_available", lambda: True),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stems_dir = stems
        self.storage = StorageService(root / "test.db")
        self.screen = player_screen.PlayerScreen(self.storage)
        patcher = patch.object(self.screen._notes, "detect")
        self.detect = patcher.start()
        self.addCleanup(patcher.stop)

        self.song = self.open_song()
        self.screen._on_notes_finished(self.song.id, "guitar", fretting.STANDARD_TUNING, NOTES)

    def open_song(self, song=None) -> Song:
        """Show ``song``, or a new one, with every stem cached."""
        if song is None:
            song = Song(title="Teste", file_path="/nonexistent.wav")
            cache = self.stems_dir / song.id
            cache.mkdir(parents=True)
            for name in ("vocals", "drums", "bass", "guitar", "piano", "other"):
                np.save(cache / f"{name}.npy", np.zeros((10, 2), np.float32))
            (cache / "metadata.json").write_text(json.dumps({"sample_rate": 44_100}))
        self.screen._song = song
        self.screen._notes_source = None
        self.screen._refresh_notes_ui()
        return song

    def choose(self, combo, text):
        """Pick the item ``text`` of ``combo`` as the user does."""
        index = combo.findText(text)
        self.assertGreaterEqual(index, 0, text)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)

    def combo_items(self, combo):
        return [combo.itemText(i) for i in range(combo.count())]

    def tearDown(self):
        self.screen.cleanup()
        self.screen.deleteLater()
        self.storage.close()
        self.temp_dir.cleanup()

    def tab_note(self, pitch):
        return next(t for t in self.screen._tab.notes if t.pitch == pitch)

    def test_tab_is_the_default_view_and_t_switches(self):
        self.assertIs(self.screen._notes_views.currentWidget(), self.screen._tab)
        self.screen._tab.window_ms = 12_000
        self.screen._toggle_notes_view()
        self.assertIs(self.screen._notes_views.currentWidget(), self.screen._note_roll)
        self.assertEqual(self.screen._note_roll.window_ms, 12_000)
        self.assertEqual(app_settings.load_setting("notes_view"), "roll")

    def test_choosing_a_position_fixes_it_and_saves_it(self):
        self.screen._on_position_chosen(self.tab_note(C4), 5)
        note = self.tab_note(C4)
        self.assertEqual((note.string, note.fret, note.fixed), (5, 15, True))
        self.assertEqual(self.storage.get_position_fixes(self.song.id, "guitar"), [PositionFix(C4, 1.0, 5)])

    def test_newest_fix_on_a_string_wins_within_a_chord(self):
        self.screen._on_position_chosen(self.tab_note(C4), 3)
        self.screen._on_position_chosen(self.tab_note(G4), 3)
        fixes = self.storage.get_position_fixes(self.song.id, "guitar")
        self.assertEqual(fixes, [PositionFix(G4, 1.01, 3)])
        self.assertEqual(self.tab_note(G4).string, 3)

    def test_fixes_on_other_chords_survive(self):
        self.screen._on_position_chosen(self.tab_note(C4), 3)
        self.screen._on_position_chosen(self.tab_note(GS4), 3)
        self.assertEqual(len(self.storage.get_position_fixes(self.song.id, "guitar")), 2)

    def test_clearing_returns_to_the_automatic_position(self):
        automatic = self.tab_note(C4)
        self.screen._on_position_chosen(automatic, 5)
        self.screen._on_position_cleared(self.tab_note(C4))
        self.assertEqual(self.storage.get_position_fixes(self.song.id, "guitar"), [])
        self.assertEqual(self.tab_note(C4)[4:7], automatic[4:7])

    def test_fix_hidden_by_the_threshold_is_not_an_orphan(self):
        self.screen._on_position_chosen(self.tab_note(GS4), 2)
        self.screen._notes_threshold.setValue(70)
        self.screen._update_tab()
        self.assertNotIn("sem nota", self.screen._notes_status.text())

    def test_orphan_fixes_are_reported(self):
        self.storage.set_position_fixes(self.song.id, "guitar", [PositionFix(50, 9.0, 4)])
        self.screen._on_notes_finished(self.song.id, "guitar", fretting.STANDARD_TUNING, NOTES)
        self.assertIn("1 posição fixada sem nota", self.screen._notes_status.text())

    def test_every_stem_with_notes_has_a_tab_instrument_entry(self):
        self.assertEqual(set(self.screen.TAB_INSTRUMENTS), set(nd.NOTE_STEMS))
        offered = [s for s, b in self.screen._notes_stem_buttons.items() if not b.isHidden()]
        self.assertEqual(offered, ["guitar", "bass", "piano", "other"])
        self.assertTrue(self.screen._notes_stem_buttons["guitar"].isChecked())

    def test_bass_shows_a_bass_tab_and_remembers_the_choice(self):
        self.screen._set_notes_stem("bass")
        self.detect.assert_called_with(self.song.id, "bass", fretting.BASS_TUNING)
        self.assertEqual(self.screen._tab.tuning, fretting.BASS_TUNING)
        self.assertEqual(self.screen._tab.notes, [])  # the guitar's notes are gone
        self.assertEqual(app_settings.load_setting("notes_stem"), "bass")
        E1 = 28
        self.screen._on_notes_finished(self.song.id, "bass", fretting.BASS_TUNING, [DetectedNote(1.0, 2.0, E1, 0.7)])
        [note] = self.screen._tab.notes
        self.assertEqual((note.string, note.fret), (4, 0))

    def test_notes_of_a_stem_no_longer_shown_are_ignored(self):
        self.screen._set_notes_stem("bass")
        self.screen._on_notes_finished(self.song.id, "guitar", fretting.STANDARD_TUNING, NOTES)
        self.assertEqual(self.screen._tab.notes, [])
        self.assertEqual(self.screen._note_roll.visible_note_count, 0)

    def test_fixes_belong_to_the_stem_they_were_made_in(self):
        self.screen._on_position_chosen(self.tab_note(C4), 5)
        self.screen._set_notes_stem("other")
        self.screen._on_notes_finished(self.song.id, "other", None, NOTES)
        self.assertFalse(self.tab_note(C4).fixed)
        self.screen._on_position_chosen(self.tab_note(G4), 2)
        self.assertEqual(
            self.storage.get_position_fixes(self.song.id, "guitar"), [PositionFix(C4, 1.0, 5)]
        )
        self.assertEqual(
            self.storage.get_position_fixes(self.song.id, "other"), [PositionFix(G4, 1.01, 2)]
        )

    def test_other_shows_on_the_guitar_tab_only_what_fits_it(self):
        C2, C7 = 36, 96
        notes = NOTES + [DetectedNote(5.0, 5.5, C2, 0.7), DetectedNote(6.0, 6.5, C7, 0.7)]
        self.screen._set_notes_stem("other")
        self.screen._on_notes_finished(self.song.id, "other", None, notes)
        self.assertEqual(self.screen._tab.tuning, fretting.STANDARD_TUNING)
        placed = {t.pitch for t in self.screen._tab.notes if t.string is not None}
        self.assertEqual(placed, {C4, G4, GS4})
        status = self.screen._notes_status.text()
        self.assertIn("5 notas", status)
        self.assertIn("2 fora da extensão", status)
        self.assertNotIn("fora da digitação", status)

    def test_piano_has_only_the_piano_roll(self):
        self.screen._set_notes_stem("piano")
        self.assertIs(self.screen._notes_views.currentWidget(), self.screen._note_roll)
        self.assertFalse(self.screen._notes_view_buttons["tab"].isEnabled())
        self.screen._toggle_notes_view()  # T does nothing
        self.assertIs(self.screen._notes_views.currentWidget(), self.screen._note_roll)
        self.screen._on_notes_finished(self.song.id, "piano", None, NOTES)
        self.assertEqual(self.screen._notes_status.text(), "3 notas")
        # The tab stays the preferred view for the instruments that have one.
        self.assertNotEqual(app_settings.load_setting("notes_view"), "roll")
        self.screen._set_notes_stem("guitar")
        self.assertIs(self.screen._notes_views.currentWidget(), self.screen._tab)
        self.assertTrue(self.screen._notes_view_buttons["tab"].isEnabled())

    def test_pickers_show_the_song_tuning(self):
        strings, tuning = self.screen._strings_combo, self.screen._tuning_combo
        self.assertEqual(self.combo_items(strings), ["6 cordas", "7 cordas", "8 cordas"])
        self.assertEqual(strings.currentText(), "6 cordas")
        self.assertEqual(tuning.currentText(), "E padrão")
        self.assertIn("Drop D", self.combo_items(tuning))
        self.assertEqual(self.storage.get_tuning(self.song.id, "guitar"), STANDARD)

    def test_seven_strings_detect_down_to_the_low_b_and_keep_fixes(self):
        self.screen._on_position_chosen(self.tab_note(C4), 5)
        self.choose(self.screen._strings_combo, "7 cordas")
        self.detect.assert_called_with(self.song.id, "guitar", SEVEN)
        self.assertEqual(self.screen._tab.tuning, SEVEN)
        self.assertEqual(self.screen._tuning_combo.currentText(), "B padrão")
        self.assertEqual(
            self.combo_items(self.screen._tuning_combo), ["B padrão", "Drop A", "A padrão"]
        )
        self.assertEqual(self.storage.get_tuning(self.song.id, "guitar"), SEVEN)
        self.assertEqual(app_settings.load_setting("tuning_guitar"), list(SEVEN))
        # Notes decoded for the old tuning are dropped.
        self.screen._on_notes_finished(self.song.id, "guitar", STANDARD, NOTES)
        self.assertEqual(self.screen._tab.notes, [])
        self.screen._on_notes_finished(
            self.song.id, "guitar", SEVEN, NOTES + [DetectedNote(5.0, 6.0, B1, 0.7)]
        )
        self.assertEqual(self.tab_note(B1)[4:6], (7, 0))
        # Strings count from the highest: the fix on the A string still holds.
        self.assertEqual(self.tab_note(C4)[4:8], (5, 15, True, True))

    def test_an_alternate_tuning_keeps_its_string_count(self):
        self.choose(self.screen._tuning_combo, "Drop D")
        self.detect.assert_called_with(self.song.id, "guitar", DROP_D)
        self.detect.reset_mock()
        self.choose(self.screen._strings_combo, "6 cordas")
        self.detect.assert_not_called()
        self.assertEqual(self.screen._tab.tuning, DROP_D)
        self.assertEqual(self.screen._tab.getPlotItem().getAxis("left").names[5], "D")

    def test_a_new_song_takes_the_last_tuning_chosen_and_keeps_its_own(self):
        second = self.open_song()
        self.choose(self.screen._strings_combo, "8 cordas")
        self.assertEqual(self.storage.get_tuning(second.id, "guitar"), EIGHT)
        # The song shown before keeps the tuning it was shown in.
        self.open_song(self.song)
        self.detect.assert_called_with(self.song.id, "guitar", STANDARD)
        self.assertEqual(self.screen._strings_combo.currentText(), "6 cordas")
        third = self.open_song()
        self.detect.assert_called_with(third.id, "guitar", EIGHT)
        self.assertEqual(self.storage.get_tuning(third.id, "guitar"), EIGHT)
        self.assertEqual(self.screen._tab.tuning, EIGHT)

    def test_other_follows_the_guitar_tuning_without_detecting_again(self):
        self.screen._set_notes_stem("other")
        self.detect.assert_called_with(self.song.id, "other", None)
        self.screen._on_notes_finished(
            self.song.id, "other", None, NOTES + [DetectedNote(5.0, 6.0, B1, 0.7)]
        )
        self.assertIsNone(self.tab_note(B1).string)
        calls = self.detect.call_count
        self.choose(self.screen._strings_combo, "7 cordas")
        self.assertEqual(self.detect.call_count, calls)
        self.assertEqual(self.screen._tab.tuning, SEVEN)
        self.assertEqual(self.tab_note(B1)[4:6], (7, 0))
        self.assertEqual(self.storage.get_tuning(self.song.id, "guitar"), SEVEN)
        self.screen._set_notes_stem("guitar")
        self.detect.assert_called_with(self.song.id, "guitar", SEVEN)

    def test_bass_has_four_to_six_strings(self):
        self.screen._set_notes_stem("bass")
        strings = self.screen._strings_combo
        self.assertEqual(self.combo_items(strings), ["4 cordas", "5 cordas", "6 cordas"])
        self.choose(strings, "6 cordas")
        six = (48, 43, 38, 33, 28, 23)
        self.detect.assert_called_with(self.song.id, "bass", six)
        self.assertEqual(
            self.screen._tab.getPlotItem().getAxis("left").names, ["C", "G", "D", "A", "E", "B"]
        )
        # The guitar keeps its own tuning.
        self.assertEqual(self.storage.get_tuning(self.song.id, "guitar"), STANDARD)

    def test_wheel_and_arrow_keys_do_not_change_the_tuning(self):
        calls = self.detect.call_count
        for combo in (self.screen._strings_combo, self.screen._tuning_combo):
            wheel = QWheelEvent(
                QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
            )
            QApplication.sendEvent(combo, wheel)
            for key in (Qt.Key_Down, Qt.Key_End):
                QApplication.sendEvent(combo, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(self.detect.call_count, calls)
        self.assertEqual(self.storage.get_tuning(self.song.id, "guitar"), STANDARD)

    def test_piano_has_no_tuning(self):
        self.screen._set_notes_stem("piano")
        self.assertTrue(self.screen._strings_combo.isHidden())
        self.assertTrue(self.screen._tuning_combo.isHidden())
        self.screen._set_notes_stem("guitar")
        self.assertFalse(self.screen._strings_combo.isHidden())

    def test_i_cycles_through_the_instruments(self):
        seen = []
        for _ in range(4):
            self.screen._cycle_notes_stem()
            seen.append(self.screen._notes_stem)
        self.assertEqual(seen, ["bass", "piano", "other", "guitar"])


if __name__ == "__main__":
    unittest.main()
