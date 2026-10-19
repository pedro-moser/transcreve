from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch

import numpy as np
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

C4, G4, GS4 = 60, 67, 68
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
        self.storage.set_position_fixes("song", fixes)
        self.assertEqual(self.storage.get_position_fixes("song"), fixes)
        self.storage.set_position_fixes("song", fixes[:1])
        self.assertEqual(self.storage.get_position_fixes("song"), fixes[:1])
        self.assertEqual(self.storage.get_position_fixes("other"), [])

    def test_deleting_a_song_deletes_its_fixes(self):
        song = Song(title="Teste", file_path="/x.wav")
        self.storage.save_song(song)
        self.storage.set_position_fixes(song.id, [PositionFix(C4, 1.0, 3)])
        self.storage.delete_song(song.id)
        self.assertEqual(self.storage.get_position_fixes(song.id), [])


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
        self.storage = StorageService(root / "test.db")
        self.screen = player_screen.PlayerScreen(self.storage)
        patcher = patch.object(self.screen._notes, "detect")
        patcher.start()
        self.addCleanup(patcher.stop)

        self.song = Song(title="Teste", file_path="/nonexistent.wav")
        cache = stems / self.song.id
        cache.mkdir(parents=True)
        np.save(cache / "guitar.npy", np.zeros((10, 2), np.float32))
        (cache / "metadata.json").write_text(json.dumps({"sample_rate": 44_100}))
        self.screen._song = self.song
        self.screen._refresh_notes_ui()
        self.screen._on_notes_finished(self.song.id, NOTES)

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
        self.assertEqual(self.storage.get_position_fixes(self.song.id), [PositionFix(C4, 1.0, 5)])

    def test_newest_fix_on_a_string_wins_within_a_chord(self):
        self.screen._on_position_chosen(self.tab_note(C4), 3)
        self.screen._on_position_chosen(self.tab_note(G4), 3)
        fixes = self.storage.get_position_fixes(self.song.id)
        self.assertEqual(fixes, [PositionFix(G4, 1.01, 3)])
        self.assertEqual(self.tab_note(G4).string, 3)

    def test_fixes_on_other_chords_survive(self):
        self.screen._on_position_chosen(self.tab_note(C4), 3)
        self.screen._on_position_chosen(self.tab_note(GS4), 3)
        self.assertEqual(len(self.storage.get_position_fixes(self.song.id)), 2)

    def test_clearing_returns_to_the_automatic_position(self):
        automatic = self.tab_note(C4)
        self.screen._on_position_chosen(automatic, 5)
        self.screen._on_position_cleared(self.tab_note(C4))
        self.assertEqual(self.storage.get_position_fixes(self.song.id), [])
        self.assertEqual(self.tab_note(C4)[4:7], automatic[4:7])

    def test_fix_hidden_by_the_threshold_is_not_an_orphan(self):
        self.screen._on_position_chosen(self.tab_note(GS4), 2)
        self.screen._notes_threshold.setValue(70)
        self.screen._update_tab()
        self.assertNotIn("sem nota", self.screen._notes_status.text())

    def test_orphan_fixes_are_reported(self):
        self.storage.set_position_fixes(self.song.id, [PositionFix(50, 9.0, 4)])
        self.screen._on_notes_finished(self.song.id, NOTES)
        self.assertIn("1 posição fixada sem nota", self.screen._notes_status.text())


if __name__ == "__main__":
    unittest.main()
