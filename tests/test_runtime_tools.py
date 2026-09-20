import hashlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
import unittest
from unittest.mock import patch

import runtime_tools


class RuntimeToolsTests(unittest.TestCase):
    def test_bundled_rubberband_is_preferred(self):
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            executable = bundle / "bin" / (
                "rubberband.exe" if os.name == "nt" else "rubberband"
            )
            executable.parent.mkdir()
            executable.write_bytes(b"binary")

            with patch.object(runtime_tools, "bundle_root", return_value=bundle):
                self.assertEqual(runtime_tools.rubberband_executable(), executable)

    def test_configured_rubberband_path_is_preferred(self):
        with TemporaryDirectory() as tmp:
            executable = Path(tmp) / "rubberband"
            executable.write_bytes(b"binary")
            with patch.dict(
                os.environ,
                {"TRANSCREVE_RUBBERBAND_PATH": str(executable)},
            ):
                self.assertEqual(runtime_tools.rubberband_executable(), executable)

    def test_system_rubberband_is_fallback(self):
        with patch.object(runtime_tools, "bundle_root", return_value=Path("/missing")):
            with patch.object(runtime_tools.shutil, "which", return_value="/usr/bin/rubberband"):
                self.assertEqual(
                    runtime_tools.rubberband_executable(),
                    Path("/usr/bin/rubberband"),
                )

    def test_configure_rubberband_updates_pyrubberband_command(self):
        fake = Path("/bundle/bin/rubberband")
        with patch.object(runtime_tools, "rubberband_executable", return_value=fake):
            configured = runtime_tools.configure_rubberband()

        import pyrubberband.pyrb as pyrb

        self.assertEqual(configured, fake)
        self.assertEqual(getattr(pyrb, "__RUBBERBAND_UTIL"), str(fake))

    def test_runtime_configuration_does_not_download_ffmpeg_by_default(self):
        with patch.object(runtime_tools, "configure_rubberband", return_value=None):
            with patch.object(runtime_tools, "ffmpeg_executable", return_value=None) as ffmpeg:
                runtime_tools.configure_runtime_tools()

        ffmpeg.assert_called_once_with(allow_download=False)

    def test_ffmpeg_download_is_verified_and_cached(self):
        payload = b"static-ffmpeg-binary"
        expected_hash = hashlib.sha256(payload).hexdigest()

        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TRANSCREVE_FFMPEG_PATH", None)
                with patch.object(runtime_tools.shutil, "which", return_value=None):
                    with patch.object(
                        runtime_tools, "_ffmpeg_platform_key", return_value=("test", "arch")
                    ):
                        with patch.dict(
                            runtime_tools.FFMPEG_RELEASES,
                            {("test", "arch"): ("ffmpeg-test", expected_hash)},
                            clear=True,
                        ):
                            with patch.object(runtime_tools, "tools_dir", return_value=root):
                                with patch.object(
                                    runtime_tools.urllib.request,
                                    "urlopen",
                                    return_value=FakeResponse(payload),
                                ) as download:
                                    executable = runtime_tools.ffmpeg_executable()
                                    cached = runtime_tools.ffmpeg_executable()

            self.assertIsNotNone(executable)
            executable = cast(Path, executable)
            self.assertEqual(executable, root / "ffmpeg-test")
            self.assertEqual(executable.read_bytes(), payload)
            self.assertEqual(cached, executable)
            download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
