import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from runtime_tools import configure_runtime_tools, resource_path
from screens.library_screen import LibraryScreen
from screens.player_screen import PlayerScreen
from services.storage_service import StorageService
import theme


class MainWindow(QMainWindow):
    def __init__(self, storage: StorageService):
        super().__init__()
        self._storage = storage
        self.setWindowTitle("Transcreve")
        self.resize(1100, 750)
        self.setMinimumSize(800, 500)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._library = LibraryScreen(storage)
        self._library.song_selected.connect(self._open_player)
        self._stack.addWidget(self._library)

        self._player = PlayerScreen(storage)
        self._player.back_requested.connect(self._show_library)
        self._stack.addWidget(self._player)

        self._stack.setCurrentWidget(self._library)

    def _open_player(self, song):
        self._player.load_song(song)
        self.setWindowTitle(f"Transcreve — {song.title}")
        self._stack.setCurrentWidget(self._player)

    def _show_library(self):
        self.setWindowTitle("Transcreve")
        self._library.refresh()
        self._stack.setCurrentWidget(self._library)

    def closeEvent(self, event):
        self._player.cleanup()
        self._storage.close()
        event.accept()


def run_smoke_test(app: QApplication, tools: dict) -> int:
    if any(path is None or not Path(path).is_file() for path in tools.values()):
        return 2

    try:
        import importlib.resources

        import demucs
        import librosa  # noqa: F401
        import numpy as np
        import pyrubberband as pyrb
        import soundfile as sf
        import torch
        import torchaudio
    except ImportError:
        return 3

    try:
        subprocess.run(
            [str(tools["rubberband"]), "--version"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [str(tools["ffmpeg"]), "-version"],
            check=True,
            capture_output=True,
        )
        manifest = importlib.resources.files(demucs).joinpath("remote/files.txt")
        if not manifest.is_file():
            return 4

        waveform = torch.zeros((2, 4_410), dtype=torch.float32)
        resampled = torchaudio.functional.resample(waveform, 44_100, 48_000)
        if resampled.shape != (2, 4_800):
            return 5

        tone = np.sin(2 * np.pi * 440 * np.arange(4_410) / 44_100).astype(
            np.float32
        )
        stretched = pyrb.time_stretch(tone, 44_100, 0.9)
        if stretched.size <= tone.size:
            return 6

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / "tone.wav"
            sf.write(wav, tone, 44_100)
            loaded, sample_rate = sf.read(wav, dtype="float32")
            if sample_rate != 44_100 or loaded.size != tone.size:
                return 7

            storage = StorageService(root / "smoke-test.db")
            window = MainWindow(storage)
            window.show()
            app.processEvents()
            window.close()
    except Exception:
        return 8
    return 0


def run_demucs_smoke_test() -> int:
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        model = get_model("htdemucs")
        model.eval()
        sample_rate = int(model.samplerate)
        smoke_frames = sample_rate // 10
        waveform = torch.zeros((1, int(model.audio_channels), smoke_frames))
        with torch.no_grad():
            estimates = apply_model(
                model,
                waveform,
                device="cpu",
                shifts=0,
                split=False,
            )
        if estimates.shape[0] != 1:
            return 11
        if estimates.shape[1] != len(model.sources):
            return 12
        if estimates.shape[2] != int(model.audio_channels):
            return 13
        if estimates.shape[3] != smoke_frames:
            return 14
        if not torch.isfinite(estimates).all():
            return 15
    except Exception:
        return 16
    return 0


def main():
    tools = configure_runtime_tools(prepare_ffmpeg="--smoke-test" in sys.argv)
    app = QApplication(sys.argv)
    app.setApplicationName("Transcreve")
    app.setApplicationDisplayName("Transcreve")
    icon_path = resource_path("assets/transcreve-icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(theme.QSS)

    if "--smoke-test" in sys.argv:
        raise SystemExit(run_smoke_test(app, tools))
    if "--demucs-smoke-test" in sys.argv:
        raise SystemExit(run_demucs_smoke_test())

    storage = StorageService()
    window = MainWindow(storage)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
