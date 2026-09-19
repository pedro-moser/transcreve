import os
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import soundfile as sf

from models.song import Song
from services.storage_service import StorageService
from services.youtube_service import YoutubeService
import theme


class LibraryScreen(QWidget):
    song_selected = Signal(object)

    def __init__(self, storage: StorageService, parent=None):
        super().__init__(parent)
        self._storage = storage
        self._songs: list[Song] = []
        self._yt = YoutubeService(self)
        self._yt.progress.connect(self._on_yt_progress)
        self._yt.finished.connect(self._on_yt_finished)
        self._yt.error.connect(self._on_yt_error)
        self._build_ui()
        self._load_songs()
        theme.on_theme_changed(self._apply_theme)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- toolbar ---
        toolbar = QWidget()
        toolbar.setStyleSheet(f"background-color: {theme.MANTLE};")
        toolbar.setFixedHeight(48)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Transcreve")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        tb_layout.addWidget(title)
        tb_layout.addStretch()

        self._btn_file = QPushButton("📂 Abrir arquivo")
        self._btn_file.setCursor(Qt.PointingHandCursor)
        self._btn_file.clicked.connect(self._add_local_file)
        tb_layout.addWidget(self._btn_file)

        self._btn_yt = QPushButton("🔗 YouTube")
        self._btn_yt.setCursor(Qt.PointingHandCursor)
        self._btn_yt.clicked.connect(self._add_youtube)
        tb_layout.addWidget(self._btn_yt)

        tb_layout.addSpacing(16)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(theme.get_theme_names())
        self._theme_combo.setCurrentText(theme.current_theme())
        self._theme_combo.setCursor(Qt.PointingHandCursor)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        tb_layout.addWidget(self._theme_combo)

        root.addWidget(toolbar)

        # --- download progress ---
        self._progress_widget = QWidget()
        self._progress_widget.setStyleSheet(f"background-color: {theme.SURFACE0};")
        p_layout = QHBoxLayout(self._progress_widget)
        p_layout.setContentsMargins(16, 8, 16, 8)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setFixedHeight(6)
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 12px;")
        p_layout.addWidget(self._progress_bar, stretch=1)
        p_layout.addWidget(self._progress_label)
        self._progress_widget.hide()
        root.addWidget(self._progress_widget)

        # --- content: list or empty state ---
        self._content_stack = QStackedWidget()

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme.BASE};
                border: none;
                padding: 8px;
            }}
            QListWidget::item {{
                background-color: {theme.MANTLE};
                border-radius: 8px;
                padding: 0px;
            }}
            QListWidget::item:hover {{
                background-color: {theme.SURFACE0};
            }}
            QListWidget::item:selected {{
                background-color: {theme.SURFACE0};
            }}
        """)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._content_stack.addWidget(self._list)

        self._empty_label = QLabel("Biblioteca vazia\nAbra um arquivo de áudio ou cole uma URL do YouTube")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {theme.SURFACE1}; font-size: 15px; padding: 60px;")
        self._content_stack.addWidget(self._empty_label)

        root.addWidget(self._content_stack, stretch=1)

    def _load_songs(self):
        self._songs = self._storage.get_songs()
        self._list.clear()
        for song in self._songs:
            self._add_song_item(song)
        if self._songs:
            self._content_stack.setCurrentWidget(self._list)
        else:
            self._content_stack.setCurrentWidget(self._empty_label)

    def _add_song_item(self, song: Song):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, song.id)
        widget = self._make_song_widget(song)
        item.setSizeHint(QSize(0, 64))
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _make_song_widget(self, song: Song) -> QWidget:
        exists = os.path.isfile(song.file_path)
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        # icon circle
        icon = QLabel("🎵" if exists else "⚠️")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"""
            background-color: {theme.SURFACE0 if exists else theme.SURFACE1};
            border-radius: 20px;
            font-size: 18px;
        """)
        layout.addWidget(icon)

        # info
        info = QVBoxLayout()
        info.setSpacing(2)
        title_lbl = QLabel(song.title)
        title_color = theme.TEXT if exists else theme.SURFACE1
        title_lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {title_color};")
        info.addWidget(title_lbl)

        parts = []
        if song.artist:
            parts.append(song.artist)
        parts.append(self._fmt_duration(song.duration_ms))
        if song.sections:
            n = len(song.sections)
            parts.append(f"{n} {'seção' if n == 1 else 'seções'}")
        sub = QLabel(" · ".join(parts))
        sub.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 12px;")
        info.addWidget(sub)
        layout.addLayout(info, stretch=1)

        # delete button
        btn_del = QPushButton("✕")
        btn_del.setFixedSize(32, 32)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet(f"""
            color: {theme.SURFACE1};
            background: transparent;
            border: none;
            font-size: 16px;
            border-radius: 16px;
        """)
        btn_del.clicked.connect(lambda _, sid=song.id: self._delete_song(sid))
        layout.addWidget(btn_del)

        return row

    def _on_item_clicked(self, item: QListWidgetItem):
        song_id = item.data(Qt.UserRole)
        song = self._storage.get_song(song_id)
        if song and os.path.isfile(song.file_path):
            self.song_selected.emit(song)

    # ── Local file ──────────────────────────────────────

    def _add_local_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir arquivo de áudio",
            str(Path.home()),
            "Áudio (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.opus *.wma);;Todos (*)",
        )
        if not path:
            return

        try:
            info = sf.info(path)
            duration_ms = int(info.duration * 1000)
        except Exception:
            duration_ms = 0

        name = Path(path).stem
        song = Song(title=name, file_path=path, duration_ms=duration_ms)
        self._storage.save_song(song)
        self._load_songs()

    # ── YouTube ─────────────────────────────────────────

    def _add_youtube(self):
        url, ok = QInputDialog.getText(
            self,
            "YouTube",
            "Cole a URL do YouTube:",
        )
        if not ok or not url.strip():
            return

        self._set_downloading(True)
        self._yt.download(url.strip())

    def _on_yt_progress(self, msg: str):
        self._progress_label.setText(msg)

    def _on_yt_finished(self, file_path: str, title: str, artist: str):
        self._set_downloading(False)

        try:
            info = sf.info(file_path)
            duration_ms = int(info.duration * 1000)
        except Exception:
            duration_ms = 0

        song = Song(
            title=title,
            file_path=file_path,
            artist=artist or None,
            duration_ms=duration_ms,
        )
        self._storage.save_song(song)
        self._load_songs()

    def _on_yt_error(self, msg: str):
        self._set_downloading(False)
        QMessageBox.warning(self, "Erro no download", msg)

    def _set_downloading(self, active: bool):
        self._progress_widget.setVisible(active)
        self._btn_file.setEnabled(not active)
        self._btn_yt.setEnabled(not active)

    # ── Delete ──────────────────────────────────────────

    def _delete_song(self, song_id: str):
        reply = QMessageBox.question(
            self,
            "Excluir música",
            "Tem certeza que deseja excluir esta música da biblioteca?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._storage.delete_song(song_id)
            self._load_songs()

    @staticmethod
    def _fmt_duration(ms: int) -> str:
        total_s = ms // 1000
        m, s = divmod(total_s, 60)
        return f"{m:02d}:{s:02d}"

    def refresh(self):
        self._load_songs()

    # ── Theme ───────────────────────────────────────────

    def _on_theme_changed(self, name: str):
        theme.set_theme(name)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(theme.QSS)

    def _apply_theme(self):
        """Reapply inline styles after theme change."""
        # toolbar
        toolbar = self.layout().itemAt(0).widget()
        if toolbar:
            toolbar.setStyleSheet(f"background-color: {theme.MANTLE};")
        # list widget
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme.BASE};
                border: none;
                padding: 8px;
            }}
            QListWidget::item {{
                background-color: {theme.MANTLE};
                border-radius: 8px;
                padding: 0px;
            }}
            QListWidget::item:hover {{
                background-color: {theme.SURFACE0};
            }}
            QListWidget::item:selected {{
                background-color: {theme.SURFACE0};
            }}
        """)
        self._empty_label.setStyleSheet(f"color: {theme.SURFACE1}; font-size: 15px; padding: 60px;")
        self._load_songs()
