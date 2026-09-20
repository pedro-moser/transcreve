from pathlib import Path

import yt_dlp
from PySide6.QtCore import QObject, QThread, Signal

from app_paths import music_dir
from runtime_tools import ffmpeg_executable


class _DownloadWorker(QObject):
    progress = Signal(str)
    finished = Signal(str, str, str)  # file_path, title, artist
    error = Signal(str)

    def __init__(self, url: str, output_dir: Path):
        super().__init__()
        self._url = url
        self._output_dir = output_dir

    def run(self):
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)

            def progress_hook(d):
                status = d.get("status", "")
                if status == "downloading":
                    pct = d.get("_percent_str", "?%").strip()
                    speed = d.get("_speed_str", "").strip()
                    self.progress.emit(f"Baixando... {pct} {speed}")
                elif status == "finished":
                    self.progress.emit("Convertendo áudio...")

            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "0",
                    }
                ],
                "outtmpl": str(self._output_dir / "%(title)s.%(ext)s"),
                "noplaylist": True,
                "progress_hooks": [progress_hook],
                "quiet": True,
                "no_warnings": True,
            }

            self.progress.emit("Preparando conversor de áudio...")
            if ffmpeg := ffmpeg_executable():
                ydl_opts["ffmpeg_location"] = str(ffmpeg)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.progress.emit("Obtendo informações...")
                info = ydl.extract_info(self._url, download=True)
                title = info.get("title", "Unknown")
                artist = info.get("uploader", "") or ""

                # find the downloaded file
                # yt-dlp renames to .mp3 after postprocessing
                requested = info.get("requested_downloads")
                if requested:
                    file_path = requested[0].get("filepath", "")
                else:
                    # fallback: find most recent mp3 in output dir
                    mp3s = sorted(self._output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
                    file_path = str(mp3s[0]) if mp3s else ""

                if file_path and Path(file_path).exists():
                    self.finished.emit(file_path, title, artist)
                else:
                    self.error.emit("Arquivo não encontrado após download")

        except Exception as e:
            self.error.emit(str(e))


class YoutubeService(QObject):
    """Downloads YouTube audio in a background thread."""

    progress = Signal(str)
    finished = Signal(str, str, str)  # file_path, title, artist
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _DownloadWorker | None = None

    @property
    def is_downloading(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def download(self, url: str):
        if self.is_downloading:
            self.error.emit("Download já em andamento")
            return

        output_dir = music_dir()

        self._thread = QThread()
        self._worker = _DownloadWorker(url, output_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _on_finished(self, file_path: str, title: str, artist: str):
        self.finished.emit(file_path, title, artist)
        self._cleanup_thread()

    def _on_error(self, msg: str):
        self.error.emit(msg)
        self._cleanup_thread()

    def _cleanup_thread(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None
