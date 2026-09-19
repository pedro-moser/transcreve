from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel

from screens.player_screen import PlayerScreen
from services.storage_service import StorageService


class ShortcutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.storage = StorageService(Path(self.temp_dir.name) / "test.db")
        self.screen = PlayerScreen(self.storage)

    def tearDown(self):
        self.screen.cleanup()
        self.screen.deleteLater()
        self.storage.close()
        self.temp_dir.cleanup()

    def test_header_exposes_shortcut_help(self):
        self.assertEqual(self.screen._btn_shortcuts.text(), "⌨ Atalhos")
        self.assertIn("atalhos", self.screen._btn_shortcuts.toolTip().lower())
        self.assertIn("atalhos", self.screen._btn_shortcuts.accessibleName().lower())
        self.assertNotEqual(self.screen._btn_shortcuts.focusPolicy(), Qt.NoFocus)
        self.assertIn(":focus", self.screen._btn_shortcuts.styleSheet())

    def test_shortcut_dialog_lists_every_registered_key(self):
        dialog = self.screen._create_shortcuts_dialog()
        visible_text = "\n".join(
            label.text() for label in dialog.findChildren(QLabel)
        )
        for expected in [
            "Espaço",
            "←",
            "→",
            "Ctrl + ←",
            "Ctrl + →",
            "[",
            "]",
            "A",
            "B",
            "L",
            "M",
            "C",
            "D",
            "Detectar acorde",
        ]:
            self.assertIn(expected, visible_text)
        dialog.deleteLater()

    def test_documented_shortcuts_match_registered_sequences(self):
        documented = {
            sequence
            for _, shortcuts in self.screen.SHORTCUT_GROUPS
            for sequence, _, _ in shortcuts
        }
        registered = {
            shortcut.key().toString(QKeySequence.PortableText)
            for shortcut in self.screen.findChildren(QShortcut)
        }
        self.assertEqual(registered, documented)

    def test_shortcut_dialog_fits_minimum_application_size(self):
        dialog = self.screen._create_shortcuts_dialog()
        dialog.adjustSize()
        self.assertLessEqual(dialog.width(), 800)
        self.assertLessEqual(dialog.height(), 500)
        self.assertTrue(dialog.isModal())
        dialog.deleteLater()

    def test_symbol_controls_have_accessible_names(self):
        controls = [
            self.screen._btn_prev,
            self.screen._btn_rew,
            self.screen._btn_play,
            self.screen._btn_fwd,
            self.screen._btn_next,
            self.screen._btn_loop_a,
            self.screen._btn_loop_b,
            self.screen._btn_loop_toggle,
        ]
        for control in controls:
            self.assertTrue(control.accessibleName(), control.text())

    def test_player_controls_have_keyboard_tooltips(self):
        self.assertIn("Espaço", self.screen._btn_play.toolTip())
        self.assertIn("←", self.screen._btn_rew.toolTip())
        self.assertIn("→", self.screen._btn_fwd.toolTip())
        self.assertIn("A", self.screen._btn_loop_a.toolTip())
        self.assertIn("B", self.screen._btn_loop_b.toolTip())
        self.assertIn("L", self.screen._btn_loop_toggle.toolTip())


if __name__ == "__main__":
    unittest.main()
