from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app_paths


class AppPathsTests(unittest.TestCase):
    def test_app_data_dir_uses_platformdirs_and_creates_directory(self):
        with TemporaryDirectory() as tmp:
            expected = Path(tmp) / "platform-data"
            with patch.object(app_paths, "user_data_path", return_value=expected):
                result = app_paths.app_data_dir()

            self.assertEqual(result, expected)
            self.assertTrue(result.is_dir())

    def test_child_paths_share_the_same_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            with patch.object(app_paths, "user_data_path", return_value=root):
                self.assertEqual(app_paths.music_dir(), root / "music")
                self.assertEqual(app_paths.stems_dir(), root / "stems")
                self.assertEqual(app_paths.tools_dir(), root / "tools")
                self.assertEqual(app_paths.settings_path(), root / "settings.json")
                self.assertEqual(app_paths.database_path(), root / "transcreve.db")


if __name__ == "__main__":
    unittest.main()
