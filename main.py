import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Transcreve")
    app.setApplicationDisplayName("Transcreve")
    app.setStyleSheet(theme.QSS)

    storage = StorageService()
    window = MainWindow(storage)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
