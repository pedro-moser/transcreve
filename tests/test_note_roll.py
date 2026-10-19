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
from models.song import Song  # noqa: E402
from screens import player_screen  # noqa: E402
from services import note_detection_service as nd  # noqa: E402
from services.note_detection_service import DetectedNote  # noqa: E402
from services.storage_service import StorageService  # noqa: E402
from widgets.note_roll_widget import NoteRollWidget, note_name  # noqa: E402

NOTES = [
    DetectedNote(1.0, 2.0, 59, 0.75),
    DetectedNote(1.01, 2.0, 60, 0.55),
    DetectedNote(3.0, 3.2, 64, 0.25),
]


class NoteRollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.roll = NoteRollWidget()
        self.roll.set_duration(60_000)

    def tearDown(self):
        self.roll.deleteLater()

    def x_range(self):
        return [round(v) for v in self.roll.getViewBox().viewRange()[0]]

    def test_note_names_use_sharps_and_octaves(self):
        self.assertEqual(note_name(60), "C4")
        self.assertEqual(note_name(61), "C#4")
        self.assertEqual(note_name(40), "E2")

    def test_threshold_hides_low_scores(self):
        self.roll.set_notes(NOTES)
        self.roll.set_threshold(0.3)
        self.assertEqual(self.roll.visible_note_count, 2)
        self.roll.set_threshold(0.2)
        self.assertEqual(self.roll.visible_note_count, 3)
        self.roll.set_threshold(0.6)
        self.assertEqual(self.roll.visible_note_count, 1)

    def test_view_follows_the_playhead(self):
        window = NoteRollWidget.DEFAULT_WINDOW_MS
        self.roll.set_position(30_000)
        left = 30_000 - NoteRollWidget.PLAYHEAD_FRACTION * window
        self.assertEqual(self.x_range(), [left, left + window])

    def test_view_stays_inside_the_song(self):
        window = NoteRollWidget.DEFAULT_WINDOW_MS
        self.roll.set_position(500)
        self.assertEqual(self.x_range(), [0, window])
        self.roll.set_position(59_900)
        self.assertEqual(self.x_range(), [60_000 - window, 60_000])

    def test_loop_shows_the_loop_and_ignores_the_playhead(self):
        self.roll.set_loop_region(10_000, 20_000, True)
        expected = self.x_range()
        self.assertLess(expected[0], 10_000)
        self.assertGreater(expected[1], 20_000)
        self.roll.set_position(15_000)
        self.assertEqual(self.x_range(), expected)
        self.roll.set_loop_region(10_000, 20_000, False)
        self.assertEqual(self.x_range()[1] - self.x_range()[0], NoteRollWidget.DEFAULT_WINDOW_MS)

    def test_note_at_finds_the_shown_note_under_the_cursor(self):
        self.roll.set_notes(NOTES)
        self.roll.set_threshold(0.3)
        self.assertEqual(self.roll.note_at(1500, 60.2)[2], 60)
        self.assertIsNone(self.roll.note_at(2500, 60))
        self.assertIsNone(self.roll.note_at(3100, 64))  # below the threshold


class PlayerNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.stems_dir = root / "stems"
        for target, name, value in (
            (nd, "STEMS_CACHE_DIR", self.stems_dir),
            (nd, "CACHE_DIR", root / "analysis"),
            (app_settings, "_SETTINGS_PATH", root / "settings.json"),
            (player_screen, "notes_available", lambda: True),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.storage = StorageService(root / "test.db")
        self.screen = player_screen.PlayerScreen(self.storage)
        self.detect = patch.object(self.screen._notes, "detect").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.screen.cleanup()
        self.screen.deleteLater()
        self.storage.close()
        self.temp_dir.cleanup()

    def open_song(self, stems=None) -> Song:
        song = Song(title="Teste", file_path="/nonexistent.wav")
        if stems:
            cache = self.stems_dir / song.id
            cache.mkdir(parents=True)
            for name in stems:
                np.save(cache / f"{name}.npy", np.zeros((10, 2), np.float32))
            (cache / "metadata.json").write_text(json.dumps({"sample_rate": 44_100}))
        self.screen._song = song
        self.screen._notes_source = None
        self.screen._refresh_notes_ui()
        return song

    def test_notes_are_offered_and_loaded_for_a_song_with_a_guitar_stem(self):
        song = self.open_song(stems=["guitar"])
        self.assertFalse(self.screen._btn_notes.isHidden())
        self.assertFalse(self.screen._notes_area.isHidden())
        self.detect.assert_called_once_with(song.id, "guitar")

    def test_a_four_stem_song_offers_the_notes_of_bass_and_other(self):
        song = self.open_song(stems=["vocals", "drums", "bass", "other"])
        self.assertFalse(self.screen._notes_area.isHidden())
        offered = [s for s, b in self.screen._notes_stem_buttons.items() if not b.isHidden()]
        self.assertEqual(offered, ["bass", "other"])
        # Without a guitar stem, the first one; the preference stays.
        self.detect.assert_called_once_with(song.id, "bass")
        self.assertIsNone(app_settings.load_setting("notes_stem"))

    def test_notes_are_not_offered_without_stems(self):
        self.open_song(stems=["vocals", "drums"])
        self.assertTrue(self.screen._btn_notes.isHidden())
        self.assertTrue(self.screen._notes_area.isHidden())
        self.detect.assert_not_called()

    def test_hiding_the_notes_keeps_the_button(self):
        self.open_song(stems=["guitar"])
        self.screen._toggle_notes()
        self.assertFalse(self.screen._btn_notes.isChecked())
        self.assertTrue(self.screen._notes_area.isHidden())
        self.assertFalse(self.screen._btn_notes.isHidden())
        self.assertFalse(app_settings.load_setting("show_notes"))

    def test_notes_for_another_song_are_ignored(self):
        song = self.open_song(stems=["guitar"])
        self.screen._on_notes_finished("another-song", "guitar", NOTES)
        self.assertEqual(self.screen._note_roll.visible_note_count, 0)
        self.screen._on_notes_finished(song.id, "guitar", NOTES)
        self.assertEqual(self.screen._note_roll.visible_note_count, 2)
        self.assertEqual(self.screen._notes_status.text(), "2 notas")


if __name__ == "__main__":
    unittest.main()
