import uuid

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from models.section import Section
from models.song import Song
from services.audio_service import AudioService
from services.chord_service import ChordService
from services.separation_service import SeparationService
from services.storage_service import StorageService
from widgets.waveform_widget import WaveformWidget
import theme


class PlayerScreen(QWidget):
    back_requested = Signal()

    SHORTCUT_GROUPS = [
        (
            "Reprodução",
            [
                ("Space", "Espaço", "Play / pausa"),
                ("Left", "←", "Voltar 5 segundos"),
                ("Right", "→", "Avançar 5 segundos"),
                ("Ctrl+Left", "Ctrl + ←", "Seção anterior"),
                ("Ctrl+Right", "Ctrl + →", "Próxima seção"),
            ],
        ),
        (
            "Velocidade",
            [
                ("[", "[", "Diminuir 0,1×"),
                ("]", "]", "Aumentar 0,1×"),
            ],
        ),
        (
            "Loop, marcações e análise",
            [
                ("A", "A", "Marcar início do loop"),
                ("B", "B", "Marcar fim do loop"),
                ("L", "L", "Ativar / desativar loop"),
                ("C", "C", "Definir cue point"),
                ("M", "M", "Adicionar seção"),
                ("D", "D", "Detectar acorde na posição atual"),
            ],
        ),
    ]

    def __init__(self, storage: StorageService, parent=None):
        super().__init__(parent)
        self._storage = storage
        self._audio = AudioService(self)
        self._chords = ChordService(self)
        self._separator = SeparationService(self)
        self._separator.progress.connect(self._on_sep_progress)
        self._separator.finished.connect(self._on_sep_finished)
        self._separator.error.connect(self._on_sep_error)
        self._song: Song | None = None
        self._selected_section: Section | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save)

        self._build_ui()
        self._connect_audio()
        self._setup_shortcuts()
        theme.on_theme_changed(self._apply_theme)

    # ── UI ──────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- header ---
        header = QWidget()
        header.setStyleSheet(f"background-color: {theme.MANTLE};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 6, 16, 6)

        btn_back = QPushButton("← Biblioteca")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(f"color: {theme.BLUE}; background: transparent; border: none;")
        btn_back.clicked.connect(self._on_back)
        h_layout.addWidget(btn_back)

        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-weight: bold; font-size: 15px;")
        h_layout.addWidget(self._title_label, stretch=1, alignment=Qt.AlignCenter)

        self._artist_label = QLabel()
        self._artist_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 12px;")
        h_layout.addWidget(self._artist_label)

        self._btn_shortcuts = QPushButton("⌨ Atalhos")
        self._btn_shortcuts.setAccessibleName("Abrir ajuda de atalhos de teclado")
        self._btn_shortcuts.setAccessibleDescription(
            "Mostra todos os comandos de teclado disponíveis no player"
        )
        self._btn_shortcuts.setCursor(Qt.PointingHandCursor)
        self._btn_shortcuts.setToolTip("Ver todos os atalhos de teclado")
        self._btn_shortcuts.clicked.connect(self._show_shortcuts)
        self._apply_shortcut_button_style()
        h_layout.addWidget(self._btn_shortcuts)

        root.addWidget(header)

        # --- waveform seekbar ---
        wave_area = QWidget()
        wave_area.setStyleSheet(f"background-color: {theme.MANTLE};")
        w_layout = QVBoxLayout(wave_area)
        w_layout.setContentsMargins(20, 12, 20, 4)

        self._waveform = WaveformWidget()
        self._waveform.seek_requested.connect(self._on_waveform_seek)
        self._waveform.loop_region_changed.connect(self._on_loop_region_drag)
        w_layout.addWidget(self._waveform)

        time_row = QHBoxLayout()
        self._pos_label = QLabel("00:00.00")
        self._pos_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-family: monospace; font-size: 12px;")
        time_row.addWidget(self._pos_label)

        self._cue_label = QLabel("")
        self._cue_label.setStyleSheet(f"color: {theme.TEAL}; font-family: monospace; font-size: 12px;")
        self._cue_label.setCursor(Qt.PointingHandCursor)
        self._cue_label.mousePressEvent = lambda _: self._clear_cue_point()
        time_row.addWidget(self._cue_label)

        time_row.addStretch()

        self._chord_label = QLabel("")
        self._chord_label.setStyleSheet(f"color: {theme.GREEN}; font-family: monospace; font-size: 14px; font-weight: bold;")
        time_row.addWidget(self._chord_label)

        time_row.addStretch()
        self._dur_label = QLabel("00:00.00")
        self._dur_label.setStyleSheet(f"color: {theme.SURFACE1}; font-family: monospace; font-size: 12px;")
        time_row.addWidget(self._dur_label)
        w_layout.addLayout(time_row)

        root.addWidget(wave_area)

        # --- playback controls ---
        controls = QWidget()
        c_layout = QHBoxLayout(controls)
        c_layout.setContentsMargins(0, 8, 0, 8)
        c_layout.setAlignment(Qt.AlignCenter)
        c_layout.setSpacing(12)

        self._btn_prev = self._icon_btn("⏮", theme.OVERLAY0, self._seek_prev_section, 36)
        self._btn_rew = self._icon_btn("⏪", theme.SUBTEXT0, lambda: self._audio.seek_relative(-5000), 36)
        self._btn_play = self._icon_btn("▶", theme.BASE, self._audio.toggle_play, 52)
        self._btn_play.setStyleSheet(
            f"background-color: {theme.BLUE}; color: {theme.BASE}; border-radius: 26px; font-size: 22px;"
        )
        self._btn_fwd = self._icon_btn("⏩", theme.SUBTEXT0, lambda: self._audio.seek_relative(5000), 36)
        self._btn_next = self._icon_btn("⏭", theme.OVERLAY0, self._seek_next_section, 36)

        self._btn_prev.setToolTip("Ctrl + ← · seção anterior")
        self._btn_prev.setAccessibleName("Ir para a seção anterior")
        self._btn_prev.setAccessibleDescription("Atalho Ctrl mais seta para a esquerda")
        self._btn_rew.setToolTip("← · voltar 5 segundos")
        self._btn_rew.setAccessibleName("Voltar 5 segundos")
        self._btn_rew.setAccessibleDescription("Atalho seta para a esquerda")
        self._btn_play.setToolTip("Espaço · play / pausa")
        self._btn_play.setAccessibleName("Reproduzir ou pausar")
        self._btn_play.setAccessibleDescription("Atalho barra de espaço")
        self._btn_fwd.setToolTip("→ · avançar 5 segundos")
        self._btn_fwd.setAccessibleName("Avançar 5 segundos")
        self._btn_fwd.setAccessibleDescription("Atalho seta para a direita")
        self._btn_next.setToolTip("Ctrl + → · próxima seção")
        self._btn_next.setAccessibleName("Ir para a próxima seção")
        self._btn_next.setAccessibleDescription("Atalho Ctrl mais seta para a direita")

        for btn in (self._btn_prev, self._btn_rew, self._btn_play, self._btn_fwd, self._btn_next):
            c_layout.addWidget(btn)

        root.addWidget(controls)

        # --- speed control ---
        speed_w = QWidget()
        sp_layout = QHBoxLayout(speed_w)
        sp_layout.setContentsMargins(20, 0, 20, 0)
        sp_layout.setSpacing(10)

        sp_icon = QLabel("⚡")
        sp_icon.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 14px;")
        sp_layout.addWidget(sp_icon)

        sp_lbl = QLabel("Velocidade")
        sp_lbl.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 12px;")
        sp_layout.addWidget(sp_lbl)

        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(25, 200)
        self._speed_slider.setSingleStep(5)
        self._speed_slider.setValue(100)
        self._speed_slider.setAccessibleName("Velocidade de reprodução")
        self._speed_slider.setAccessibleDescription(
            "Use colchete esquerdo para diminuir e colchete direito para aumentar"
        )
        self._speed_slider.setToolTip("[ diminui · ] aumenta a velocidade")
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        sp_layout.addWidget(self._speed_slider, stretch=1)

        self._speed_label = QLabel("1.00x")
        self._speed_label.setStyleSheet(f"color: {theme.BLUE}; font-family: monospace; font-size: 13px;")
        self._speed_label.setFixedWidth(48)
        sp_layout.addWidget(self._speed_label)

        btn_reset_speed = QPushButton("1x")
        btn_reset_speed.setAccessibleName("Redefinir velocidade para uma vez")
        btn_reset_speed.setFixedSize(32, 24)
        btn_reset_speed.setStyleSheet(f"color: {theme.OVERLAY0}; background: transparent; border: 1px solid {theme.SURFACE1}; border-radius: 4px; font-size: 11px;")
        btn_reset_speed.setCursor(Qt.PointingHandCursor)
        btn_reset_speed.clicked.connect(lambda: self._set_speed(1.0))
        sp_layout.addWidget(btn_reset_speed)

        root.addWidget(speed_w)

        # --- loop controls ---
        loop_w = QWidget()
        loop_w.setStyleSheet(f"background-color: {theme.BASE};")
        lp_layout = QHBoxLayout(loop_w)
        lp_layout.setContentsMargins(20, 8, 20, 8)
        lp_layout.setAlignment(Qt.AlignCenter)
        lp_layout.setSpacing(16)

        self._btn_loop_a = QPushButton("A")
        self._btn_loop_a.setAccessibleName("Marcar início do loop")
        self._btn_loop_a.setAccessibleDescription("Atalho A")
        self._btn_loop_a.setFixedSize(48, 32)
        self._btn_loop_a.setCursor(Qt.PointingHandCursor)
        self._btn_loop_a.setToolTip("A · marcar início do loop")
        self._btn_loop_a.clicked.connect(self._set_loop_start)
        lp_layout.addWidget(self._btn_loop_a)

        self._btn_loop_toggle = QPushButton("Loop (L)")
        self._btn_loop_toggle.setAccessibleName("Ativar ou desativar loop")
        self._btn_loop_toggle.setAccessibleDescription("Atalho L")
        self._btn_loop_toggle.setFixedHeight(32)
        self._btn_loop_toggle.setCursor(Qt.PointingHandCursor)
        self._btn_loop_toggle.setToolTip("L · ativar ou desativar o loop")
        self._btn_loop_toggle.clicked.connect(self._toggle_loop)
        lp_layout.addWidget(self._btn_loop_toggle)

        self._btn_loop_b = QPushButton("B")
        self._btn_loop_b.setAccessibleName("Marcar fim do loop")
        self._btn_loop_b.setAccessibleDescription("Atalho B")
        self._btn_loop_b.setFixedSize(48, 32)
        self._btn_loop_b.setCursor(Qt.PointingHandCursor)
        self._btn_loop_b.setToolTip("B · marcar fim do loop")
        self._btn_loop_b.clicked.connect(self._set_loop_end)
        lp_layout.addWidget(self._btn_loop_b)

        btn_clear_loop = QPushButton("✕")
        btn_clear_loop.setAccessibleName("Limpar marcações do loop")
        btn_clear_loop.setFixedSize(28, 28)
        btn_clear_loop.setCursor(Qt.PointingHandCursor)
        btn_clear_loop.setStyleSheet(f"color: {theme.SURFACE1}; background: transparent; border: none;")
        btn_clear_loop.clicked.connect(self._clear_loop)
        lp_layout.addWidget(btn_clear_loop)

        root.addWidget(loop_w)

        # --- stems panel ---
        self._stems_widget = QWidget()
        self._stems_widget.setStyleSheet(f"background-color: {theme.BASE};")
        stems_layout = QHBoxLayout(self._stems_widget)
        stems_layout.setContentsMargins(20, 6, 20, 6)
        stems_layout.setAlignment(Qt.AlignCenter)
        stems_layout.setSpacing(10)

        self._btn_separate = QPushButton("🎛 Separar instrumentos")
        self._btn_separate.setCursor(Qt.PointingHandCursor)
        self._btn_separate.clicked.connect(self._start_separation)
        stems_layout.addWidget(self._btn_separate)

        self._sep_status = QLabel("")
        self._sep_status.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 11px;")
        stems_layout.addWidget(self._sep_status)

        stems_layout.addStretch()

        self._stem_buttons: dict[str, QPushButton] = {}
        stem_icons = {"vocals": "🎤", "drums": "🥁", "bass": "🎸", "other": "🎹"}
        for name in ["vocals", "drums", "bass", "other"]:
            btn = QPushButton(f"{stem_icons[name]} {name.capitalize()}")
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.clicked.connect(lambda _, n=name: self._on_stem_toggle(n))
            btn.hide()
            stems_layout.addWidget(btn)
            self._stem_buttons[name] = btn

        self._btn_unsolo = QPushButton("Todos")
        self._btn_unsolo.setFixedHeight(28)
        self._btn_unsolo.setCursor(Qt.PointingHandCursor)
        self._btn_unsolo.clicked.connect(self._unsolo_all)
        self._btn_unsolo.hide()
        stems_layout.addWidget(self._btn_unsolo)

        root.addWidget(self._stems_widget)

        # --- bottom panel: sections + notes ---
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {theme.SURFACE0}; width: 2px; }}")

        # sections panel
        self._sections_panel = QWidget()
        sec_layout = QVBoxLayout(self._sections_panel)
        sec_layout.setContentsMargins(12, 8, 4, 12)
        sec_layout.setSpacing(4)

        sec_header = QHBoxLayout()
        sec_title = QLabel("Seções")
        sec_title.setStyleSheet(f"color: {theme.OVERLAY0}; font-weight: bold; font-size: 13px;")
        sec_header.addWidget(sec_title)
        sec_header.addStretch()

        btn_add_sec = QPushButton("+")
        btn_add_sec.setAccessibleName("Adicionar seção na posição atual")
        btn_add_sec.setAccessibleDescription("Atalho M")
        btn_add_sec.setFixedSize(24, 24)
        btn_add_sec.setCursor(Qt.PointingHandCursor)
        btn_add_sec.setToolTip("M · adicionar seção na posição atual")
        btn_add_sec.setStyleSheet(f"color: {theme.GREEN}; background: transparent; border: 1px solid {theme.GREEN}; border-radius: 4px; font-size: 14px; font-weight: bold;")
        btn_add_sec.clicked.connect(self._add_section)
        sec_header.addWidget(btn_add_sec)
        sec_layout.addLayout(sec_header)

        self._sections_list = QListWidget()
        self._sections_list.setStyleSheet(f"""
            QListWidget {{ background-color: {theme.BASE}; border: none; }}
            QListWidget::item {{ padding: 4px 8px; border-radius: 4px; margin: 1px 0; }}
            QListWidget::item:selected {{ background-color: {theme.SURFACE0}; }}
            QListWidget::item:hover {{ background-color: {theme.SURFACE0}; }}
        """)
        self._sections_list.itemClicked.connect(self._on_section_clicked)
        self._sections_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._sections_list.customContextMenuRequested.connect(self._on_section_context_menu)
        sec_layout.addWidget(self._sections_list, stretch=1)

        # section notes
        self._sec_notes_label = QLabel()
        self._sec_notes_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 11px; padding-top: 4px;")
        self._sec_notes_label.hide()
        sec_layout.addWidget(self._sec_notes_label)

        self._sec_notes_edit = QTextEdit()
        self._sec_notes_edit.setMaximumHeight(80)
        self._sec_notes_edit.setPlaceholderText("Notas da seção...")
        self._sec_notes_edit.setStyleSheet(f"font-size: 12px;")
        self._sec_notes_edit.textChanged.connect(self._on_section_notes_changed)
        self._sec_notes_edit.hide()
        sec_layout.addWidget(self._sec_notes_edit)

        self._empty_sec_label = QLabel("Sem seções\nPressione M para adicionar")
        self._empty_sec_label.setAlignment(Qt.AlignCenter)
        self._empty_sec_label.setStyleSheet(f"color: {theme.SURFACE1}; font-size: 12px; padding: 20px;")
        sec_layout.addWidget(self._empty_sec_label)

        splitter.addWidget(self._sections_panel)

        # notes panel
        notes_w = QWidget()
        n_layout = QVBoxLayout(notes_w)
        n_layout.setContentsMargins(4, 8, 12, 12)

        n_header = QHBoxLayout()
        n_label = QLabel("Notas")
        n_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-weight: bold; font-size: 13px;")
        n_header.addWidget(n_label)
        n_header.addStretch()
        n_layout.addLayout(n_header)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Anotações gerais sobre a música...")
        self._notes_edit.setStyleSheet("font-size: 13px; line-height: 1.5;")
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        n_layout.addWidget(self._notes_edit, stretch=1)

        splitter.addWidget(notes_w)
        splitter.setSizes([280, 500])

        root.addWidget(splitter, stretch=1)

        self._update_loop_ui()

    def _icon_btn(self, text: str, color: str, callback, size: int = 36) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(size, size)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"background: transparent; color: {color}; border: none; font-size: 16px;"
        )
        btn.clicked.connect(callback)
        return btn

    def _apply_shortcut_button_style(self):
        self._btn_shortcuts.setStyleSheet(
            f"""
            QPushButton {{
                color: {theme.SUBTEXT0};
                background-color: {theme.SURFACE0};
                border: 1px solid {theme.SURFACE1};
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {theme.TEXT};
                border-color: {theme.BLUE};
            }}
            QPushButton:focus {{
                color: {theme.TEXT};
                border: 2px solid {theme.YELLOW};
            }}
            """
        )

    def _create_shortcuts_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setObjectName("shortcutDialog")
        dialog.setWindowTitle("Atalhos de teclado")
        dialog.setModal(True)
        dialog.setFixedWidth(780)
        dialog.resize(780, 470)
        dialog.setMaximumHeight(500)
        dialog.setStyleSheet(f"background-color: {theme.BASE}; color: {theme.TEXT};")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)

        title = QLabel("Atalhos de teclado")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("Use estes comandos enquanto o player estiver aberto.")
        subtitle.setStyleSheet(f"color: {theme.SUBTEXT0}; font-size: 12px;")
        layout.addWidget(subtitle)

        columns = QHBoxLayout()
        columns.setSpacing(28)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        left_column.setSpacing(5)
        right_column.setSpacing(5)
        columns.addLayout(left_column, stretch=1)
        columns.addLayout(right_column, stretch=1)

        for group_index, (group_name, shortcuts) in enumerate(self.SHORTCUT_GROUPS):
            column = left_column if group_index < 2 else right_column
            group_label = QLabel(group_name)
            group_label.setStyleSheet(
                f"color: {theme.BLUE}; font-size: 13px; font-weight: bold; padding-top: 6px;"
            )
            column.addWidget(group_label)

            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(5)
            for row, (_, display_key, description) in enumerate(shortcuts):
                key_label = QLabel(display_key)
                key_label.setAlignment(Qt.AlignCenter)
                key_label.setFixedSize(104, 28)
                key_label.setStyleSheet(
                    f"""
                    background-color: {theme.SURFACE0};
                    color: {theme.TEXT};
                    border: 1px solid {theme.SURFACE1};
                    border-radius: 5px;
                    font-family: monospace;
                    font-size: 12px;
                    font-weight: bold;
                    """
                )
                description_label = QLabel(description)
                description_label.setWordWrap(True)
                description_label.setStyleSheet(
                    f"color: {theme.SUBTEXT0}; font-size: 12px;"
                )
                grid.addWidget(key_label, row, 0)
                grid.addWidget(description_label, row, 1)
            grid.setColumnStretch(1, 1)
            column.addLayout(grid)

        left_column.addStretch()
        right_column.addStretch()
        layout.addLayout(columns, stretch=1)

        close_button = QPushButton("Fechar")
        close_button.setAccessibleName("Fechar ajuda de atalhos")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(dialog.accept)
        close_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {theme.BLUE};
                color: {theme.BASE};
                border: 2px solid transparent;
                border-radius: 6px;
                padding: 7px 18px;
                font-weight: bold;
            }}
            QPushButton:focus {{
                border-color: {theme.YELLOW};
            }}
            """
        )
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        return dialog

    def _show_shortcuts(self):
        dialog = self._create_shortcuts_dialog()
        dialog.exec()

    # ── Shortcuts ───────────────────────────────────────

    def _setup_shortcuts(self):
        actions = {
            "Space": self._audio.toggle_play,
            "Left": lambda: self._audio.seek_relative(-5000),
            "Right": lambda: self._audio.seek_relative(5000),
            "Ctrl+Left": self._seek_prev_section,
            "Ctrl+Right": self._seek_next_section,
            "[": lambda: self._set_speed(self._audio.speed - 0.1),
            "]": lambda: self._set_speed(self._audio.speed + 0.1),
            "L": self._toggle_loop,
            "A": self._set_loop_start,
            "B": self._set_loop_end,
            "M": self._add_section,
            "C": self._set_cue_point,
            "D": self._detect_chord,
        }
        for _, shortcuts in self.SHORTCUT_GROUPS:
            for sequence, _, _ in shortcuts:
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(actions[sequence])

    # ── Connect audio signals ───────────────────────────

    def _connect_audio(self):
        self._audio.position_changed.connect(self._on_position)
        self._audio.duration_changed.connect(self._on_duration)
        self._audio.playing_changed.connect(self._on_playing)
        self._audio.error_occurred.connect(self._on_audio_error)
        self._audio.loading_changed.connect(self._on_loading)

    def _on_audio_error(self, msg: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Erro de áudio", msg)

    def _on_loading(self, loading: bool):
        if loading:
            self._pos_label.setText("Carregando...")
            self._btn_play.setEnabled(False)
        else:
            self._pos_label.setText("00:00.00")
            self._btn_play.setEnabled(True)
            # now that audio is loaded, render waveform
            if self._audio.audio_data is not None:
                self._waveform.load_waveform(
                    self._audio.audio_data,
                    self._audio.sample_rate,
                    self._audio.duration_ms,
                )
                # start chord analysis in background
                self._chord_label.setText("")
                self._chords.analyze(self._audio.audio_data, self._audio.sample_rate)
            if self._song:
                self._refresh_sections_ui()

    def _on_position(self, ms: int):
        self._pos_label.setText(self._fmt(ms))
        self._waveform.set_position(ms)

    def _on_duration(self, ms: int):
        self._dur_label.setText(self._fmt(ms))

    def _on_playing(self, playing: bool):
        self._btn_play.setText("⏸" if playing else "▶")

    # ── Waveform seek ───────────────────────────────────

    def _on_waveform_seek(self, ms: int):
        self._audio.seek(ms)
        self._pos_label.setText(self._fmt(ms))

    def _on_loop_region_drag(self, start_ms: int, end_ms: int):
        self._audio.set_loop_start(start_ms)
        self._audio.set_loop_end(end_ms)
        if not self._audio.loop_enabled:
            self._audio.toggle_loop()
        self._update_loop_ui()

    # ── Speed ───────────────────────────────────────────

    def _on_speed_slider(self, value: int):
        speed = value / 100
        self._speed_label.setText(f"{speed:.2f}x")
        # set_speed is now non-blocking: instant interpolation + rubberband in background
        self._audio.set_speed(speed)

    def _set_speed(self, speed: float):
        speed = round(max(0.25, min(2.0, speed)), 2)
        self._speed_slider.setValue(int(speed * 100))

    # ── Loop ────────────────────────────────────────────

    def _set_loop_start(self):
        self._audio.set_loop_start()
        self._update_loop_ui()

    def _set_loop_end(self):
        self._audio.set_loop_end()
        self._update_loop_ui()

    def _toggle_loop(self):
        self._audio.toggle_loop()
        self._update_loop_ui()

    def _clear_loop(self):
        self._audio.clear_loop()
        self._update_loop_ui()

    def _update_loop_ui(self):
        a = self._audio.loop_start
        b = self._audio.loop_end
        enabled = self._audio.loop_enabled

        self._waveform.set_loop_region(a, b, enabled)

        a_text = f"A {self._fmt_short(a)}" if a is not None else "A"
        b_text = f"B {self._fmt_short(b)}" if b is not None else "B"
        a_color = theme.PEACH if a is not None else theme.OVERLAY0
        b_color = theme.PEACH if b is not None else theme.OVERLAY0

        self._btn_loop_a.setText(a_text)
        self._btn_loop_a.setStyleSheet(
            f"color: {a_color}; background: transparent; border: 1px solid {a_color}; border-radius: 6px; font-size: 11px; font-family: monospace;"
        )
        self._btn_loop_b.setText(b_text)
        self._btn_loop_b.setStyleSheet(
            f"color: {b_color}; background: transparent; border: 1px solid {b_color}; border-radius: 6px; font-size: 11px; font-family: monospace;"
        )

        if enabled:
            self._btn_loop_toggle.setStyleSheet(
                f"color: {theme.PEACH}; background-color: rgba(250,179,135,30); border: 1px solid {theme.PEACH}; border-radius: 6px; font-size: 12px;"
            )
        else:
            self._btn_loop_toggle.setStyleSheet(
                f"color: {theme.OVERLAY0}; background: transparent; border: 1px solid {theme.SURFACE1}; border-radius: 6px; font-size: 12px;"
            )

    # ── Cue point ───────────────────────────────────────

    def _set_cue_point(self):
        self._audio.set_cue_point()
        cp = self._audio.cue_point
        self._cue_label.setText(f"cue: {self._fmt_short(cp)}" if cp is not None else "")
        self._waveform.set_cue_point(cp)

    def _clear_cue_point(self):
        self._audio.clear_cue_point()
        self._cue_label.setText("")
        self._waveform.set_cue_point(None)

    # ── Chord detection ─────────────────────────────────

    def _detect_chord(self):
        chord = self._chords.detect_at(self._audio.position_ms)
        self._chord_label.setText(chord)

    # ── Stem separation ─────────────────────────────────

    def _start_separation(self):
        if not self._song or self._separator.is_processing:
            return
        self._btn_separate.setEnabled(False)
        self._sep_status.setText("Iniciando...")
        self._separator.separate(self._song.file_path, self._song.id)

    def _on_sep_progress(self, msg: str):
        self._sep_status.setText(msg)

    def _on_sep_finished(self, stems: dict):
        self._sep_status.setText("")
        self._btn_separate.hide()
        self._audio.load_stems(stems)
        for name, btn in self._stem_buttons.items():
            btn.setChecked(True)
            btn.show()
            self._update_stem_btn_style(name)
        self._btn_unsolo.show()

    def _on_sep_error(self, msg: str):
        self._btn_separate.setEnabled(True)
        self._sep_status.setText(f"Erro: {msg[:60]}")

    def _on_stem_toggle(self, name: str):
        from PySide6.QtWidgets import QApplication as _QApp
        modifiers = _QApp.keyboardModifiers()
        if modifiers & Qt.ControlModifier:
            self._audio.solo_stem(name)
            for n, btn in self._stem_buttons.items():
                btn.setChecked(n == name)
                self._update_stem_btn_style(n)
        else:
            self._audio.toggle_stem(name)
            btn = self._stem_buttons[name]
            btn.setChecked(not self._audio.is_stem_muted(name))
            self._update_stem_btn_style(name)

    def _unsolo_all(self):
        self._audio.unsolo_all()
        for name, btn in self._stem_buttons.items():
            btn.setChecked(True)
            self._update_stem_btn_style(name)

    def _update_stem_btn_style(self, name: str):
        btn = self._stem_buttons[name]
        active = not self._audio.is_stem_muted(name)
        if active:
            btn.setStyleSheet(
                f"color: {theme.TEXT}; background-color: {theme.SURFACE0}; border: 1px solid {theme.BLUE}; border-radius: 6px; font-size: 11px; padding: 2px 8px;"
            )
        else:
            btn.setStyleSheet(
                f"color: {theme.SURFACE1}; background-color: transparent; border: 1px solid {theme.SURFACE1}; border-radius: 6px; font-size: 11px; padding: 2px 8px;"
            )

    # ── Sections ────────────────────────────────────────

    def _add_section(self):
        if not self._song:
            return
        n = len(self._song.sections) + 1
        color = theme.SECTION_COLORS[(n - 1) % len(theme.SECTION_COLORS)]
        sec = Section(
            id=str(uuid.uuid4()),
            name=f"Seção {n}",
            start_ms=self._audio.position_ms,
            color_hex=color,
        )
        self._song.sections.append(sec)
        self._song.sections.sort(key=lambda s: s.start_ms)
        self._selected_section = sec
        self._save()
        self._refresh_sections_ui()

    def _refresh_sections_ui(self):
        if not self._song:
            return
        sections = sorted(self._song.sections, key=lambda s: s.start_ms)
        has_sections = len(sections) > 0

        self._sections_list.setVisible(has_sections)
        self._empty_sec_label.setVisible(not has_sections)

        self._sections_list.blockSignals(True)
        self._sections_list.clear()
        selected_row = -1
        for i, sec in enumerate(sections):
            text = f"  {sec.name}  —  {self._fmt_short(sec.start_ms)}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, sec.id)
            item.setForeground(QColor(sec.color_hex))
            self._sections_list.addItem(item)
            if self._selected_section and sec.id == self._selected_section.id:
                selected_row = i
        if selected_row >= 0:
            self._sections_list.setCurrentRow(selected_row)
        self._sections_list.blockSignals(False)

        # update section notes panel
        if self._selected_section and has_sections:
            self._sec_notes_label.setText(f"Notas: {self._selected_section.name}")
            self._sec_notes_label.show()
            self._sec_notes_edit.blockSignals(True)
            self._sec_notes_edit.setPlainText(self._selected_section.notes)
            self._sec_notes_edit.blockSignals(False)
            self._sec_notes_edit.show()
        else:
            self._sec_notes_label.hide()
            self._sec_notes_edit.hide()

        # update waveform markers
        self._waveform.set_sections(self._song.sections)

    def _on_section_clicked(self, item: QListWidgetItem):
        sec_id = item.data(Qt.UserRole)
        sec = self._find_section(sec_id)
        if sec:
            self._selected_section = sec
            self._audio.seek(sec.start_ms)
            self._refresh_sections_ui()

    def _on_section_context_menu(self, pos):
        item = self._sections_list.itemAt(pos)
        if not item:
            return
        sec_id = item.data(Qt.UserRole)
        sec = self._find_section(sec_id)
        if not sec:
            return

        menu = QMenu(self)
        act_rename = menu.addAction("Renomear")
        act_move = menu.addAction("Mover para posição atual")
        menu.addSeparator()
        act_delete = menu.addAction("Excluir")
        act_delete.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_TrashIcon))

        action = menu.exec(self._sections_list.mapToGlobal(pos))
        if action == act_rename:
            self._rename_section(sec)
        elif action == act_move:
            sec.start_ms = self._audio.position_ms
            self._song.sections.sort(key=lambda s: s.start_ms)
            self._save()
            self._refresh_sections_ui()
        elif action == act_delete:
            self._delete_section(sec)

    def _rename_section(self, sec: Section):
        name, ok = QInputDialog.getText(self, "Renomear seção", "Nome:", text=sec.name)
        if ok and name.strip():
            sec.name = name.strip()
            self._save()
            self._refresh_sections_ui()

    def _delete_section(self, sec: Section):
        if not self._song:
            return
        self._song.sections = [s for s in self._song.sections if s.id != sec.id]
        if self._selected_section and self._selected_section.id == sec.id:
            self._selected_section = None
        self._save()
        self._refresh_sections_ui()

    def _on_section_notes_changed(self):
        if self._selected_section:
            self._selected_section.notes = self._sec_notes_edit.toPlainText()
            self._save_timer.start()

    def _find_section(self, sec_id: str) -> Section | None:
        if not self._song:
            return None
        for s in self._song.sections:
            if s.id == sec_id:
                return s
        return None

    # ── Section navigation ──────────────────────────────

    def _seek_prev_section(self):
        if not self._song or not self._song.sections:
            return
        pos = self._audio.position_ms - 500
        prev = None
        for s in sorted(self._song.sections, key=lambda x: x.start_ms):
            if s.start_ms < pos:
                prev = s
        if prev:
            self._selected_section = prev
            self._audio.seek(prev.start_ms)
            self._refresh_sections_ui()

    def _seek_next_section(self):
        if not self._song or not self._song.sections:
            return
        pos = self._audio.position_ms + 100
        for s in sorted(self._song.sections, key=lambda x: x.start_ms):
            if s.start_ms > pos:
                self._selected_section = s
                self._audio.seek(s.start_ms)
                self._refresh_sections_ui()
                return

    # ── Notes ───────────────────────────────────────────

    def _on_notes_changed(self):
        self._save_timer.start()

    def _save(self):
        if self._song is None:
            return
        self._song.notes = self._notes_edit.toPlainText()
        self._storage.save_song(self._song)

    # ── Navigation ──────────────────────────────────────

    def load_song(self, song: Song):
        self._song = song
        self._selected_section = None
        self._title_label.setText(song.title)
        self._artist_label.setText(song.artist or "")
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(song.notes)
        self._notes_edit.blockSignals(False)
        self._clear_cue_point()
        self._clear_loop()
        self._set_speed(1.0)

        # reset stems UI
        for btn in self._stem_buttons.values():
            btn.hide()
        self._btn_unsolo.hide()
        self._btn_separate.show()
        self._btn_separate.setEnabled(True)
        self._sep_status.setText("")
        if self._separator.has_cache(song.id):
            self._btn_separate.setText("🎛 Carregar stems")

        # async load — waveform rendered in _on_loading callback
        self._audio.load(song.file_path)

    def _on_back(self):
        self._save()
        self._audio.stop()
        self.back_requested.emit()

    # ── Formatting ──────────────────────────────────────

    @staticmethod
    def _fmt(ms: int) -> str:
        total_s = ms / 1000
        m = int(total_s) // 60
        s = total_s - m * 60
        return f"{m:02d}:{s:05.2f}"

    @staticmethod
    def _fmt_short(ms: int | None) -> str:
        if ms is None:
            return ""
        total_s = ms / 1000
        m = int(total_s) // 60
        s = total_s - m * 60
        return f"{m}:{s:05.2f}"

    # ── Theme ───────────────────────────────────────────

    def _apply_theme(self):
        """Reapply all inline styles after theme change."""
        self._pos_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-family: monospace; font-size: 12px;")
        self._cue_label.setStyleSheet(f"color: {theme.TEAL}; font-family: monospace; font-size: 12px;")
        self._chord_label.setStyleSheet(f"color: {theme.GREEN}; font-family: monospace; font-size: 14px; font-weight: bold;")
        self._dur_label.setStyleSheet(f"color: {theme.SURFACE1}; font-family: monospace; font-size: 12px;")
        self._speed_label.setStyleSheet(f"color: {theme.BLUE}; font-family: monospace; font-size: 13px;")
        self._artist_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 12px;")
        self._sep_status.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 11px;")
        self._apply_shortcut_button_style()
        self._empty_sec_label.setStyleSheet(f"color: {theme.SURFACE1}; font-size: 12px; padding: 20px;")
        self._sec_notes_label.setStyleSheet(f"color: {theme.OVERLAY0}; font-size: 11px; padding-top: 4px;")
        self._btn_play.setStyleSheet(
            f"background-color: {theme.BLUE}; color: {theme.BASE}; border-radius: 26px; font-size: 22px;"
        )
        self._update_loop_ui()
        # update stem button styles
        if self._audio.has_stems:
            for name in self._stem_buttons:
                self._update_stem_btn_style(name)
        # update waveform
        self._waveform.refresh_theme()
        # update sections list
        self._sections_list.setStyleSheet(f"""
            QListWidget {{ background-color: {theme.BASE}; border: none; }}
            QListWidget::item {{ padding: 4px 8px; border-radius: 4px; margin: 1px 0; }}
            QListWidget::item:selected {{ background-color: {theme.SURFACE0}; }}
            QListWidget::item:hover {{ background-color: {theme.SURFACE0}; }}
        """)
        if self._song:
            self._refresh_sections_ui()

    # ── Cleanup ─────────────────────────────────────────

    def cleanup(self):
        self._save()
        self._audio.dispose()
        self._chords.dispose()
