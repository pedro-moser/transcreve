from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

import services.youtube_service as youtube_service


class YoutubeRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_worker_passes_packaged_ffmpeg_to_ytdlp(self):
        captured = {}

        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            downloaded = output_dir / "Track.mp3"
            downloaded.write_bytes(b"mp3")

            class FakeYoutubeDL:
                def __init__(self, options):
                    captured.update(options)

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, *_args, **_kwargs):
                    return {
                        "title": "Track",
                        "uploader": "Artist",
                        "requested_downloads": [{"filepath": str(downloaded)}],
                    }

            results = []
            errors = []
            worker = youtube_service._DownloadWorker(
                "https://example.invalid/video", output_dir
            )
            worker.finished.connect(lambda *args: results.append(args))
            worker.error.connect(errors.append)

            with patch.object(
                youtube_service,
                "ffmpeg_executable",
                return_value=Path("/bundle/bin/ffmpeg"),
            ):
                with patch.object(youtube_service.yt_dlp, "YoutubeDL", FakeYoutubeDL):
                    worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(captured["ffmpeg_location"], str(Path("/bundle/bin/ffmpeg")))
        self.assertEqual(results[0][1:], ("Track", "Artist"))


if __name__ == "__main__":
    unittest.main()
