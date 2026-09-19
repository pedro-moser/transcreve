import json
from pathlib import Path

_SETTINGS_PATH = Path.home() / ".local" / "share" / "transcreve" / "settings.json"

# ── Theme palettes ──────────────────────────────────────

THEMES = {
    "Catppuccin Mocha": {
        "BASE": "#181825", "MANTLE": "#1E1E2E",
        "SURFACE0": "#313244", "SURFACE1": "#45475A", "SURFACE2": "#585B70",
        "OVERLAY0": "#6C7086", "SUBTEXT0": "#A6ADC8", "TEXT": "#CDD6F4",
        "BLUE": "#89B4FA", "GREEN": "#A6E3A1", "PEACH": "#FAB387",
        "TEAL": "#94E2D5", "RED": "#F38BA8", "MAUVE": "#CBA6F7", "YELLOW": "#F9E2AF",
    },
    "Catppuccin Latte": {
        "BASE": "#EFF1F5", "MANTLE": "#E6E9EF",
        "SURFACE0": "#CCD0DA", "SURFACE1": "#BCC0CC", "SURFACE2": "#ACB0BE",
        "OVERLAY0": "#9CA0B0", "SUBTEXT0": "#6C6F85", "TEXT": "#4C4F69",
        "BLUE": "#1E66F5", "GREEN": "#40A02B", "PEACH": "#FE640B",
        "TEAL": "#179299", "RED": "#D20F39", "MAUVE": "#8839EF", "YELLOW": "#DF8E1D",
    },
    "Dracula": {
        "BASE": "#282A36", "MANTLE": "#21222C",
        "SURFACE0": "#343746", "SURFACE1": "#44475A", "SURFACE2": "#565970",
        "OVERLAY0": "#6272A4", "SUBTEXT0": "#A4B1D6", "TEXT": "#F8F8F2",
        "BLUE": "#8BE9FD", "GREEN": "#50FA7B", "PEACH": "#FFB86C",
        "TEAL": "#8BE9FD", "RED": "#FF5555", "MAUVE": "#BD93F9", "YELLOW": "#F1FA8C",
    },
    "Nord": {
        "BASE": "#2E3440", "MANTLE": "#3B4252",
        "SURFACE0": "#434C5E", "SURFACE1": "#4C566A", "SURFACE2": "#5C6678",
        "OVERLAY0": "#7B88A1", "SUBTEXT0": "#9DA6B8", "TEXT": "#ECEFF4",
        "BLUE": "#88C0D0", "GREEN": "#A3BE8C", "PEACH": "#D08770",
        "TEAL": "#8FBCBB", "RED": "#BF616A", "MAUVE": "#B48EAD", "YELLOW": "#EBCB8B",
    },
}

# ── Active theme (module-level variables) ───────────────

BASE = ""
MANTLE = ""
SURFACE0 = ""
SURFACE1 = ""
SURFACE2 = ""
OVERLAY0 = ""
SUBTEXT0 = ""
TEXT = ""
BLUE = ""
GREEN = ""
PEACH = ""
TEAL = ""
RED = ""
MAUVE = ""
YELLOW = ""
SECTION_COLORS: list[str] = []
QSS = ""

_current_theme = ""
_on_change_callbacks: list = []


def on_theme_changed(callback):
    """Register a callback to be called when theme changes."""
    _on_change_callbacks.append(callback)


def get_theme_names() -> list[str]:
    return list(THEMES.keys())


def current_theme() -> str:
    return _current_theme


def set_theme(name: str):
    global BASE, MANTLE, SURFACE0, SURFACE1, SURFACE2
    global OVERLAY0, SUBTEXT0, TEXT
    global BLUE, GREEN, PEACH, TEAL, RED, MAUVE, YELLOW
    global SECTION_COLORS, QSS, _current_theme

    if name not in THEMES:
        name = "Catppuccin Mocha"

    p = THEMES[name]
    _current_theme = name
    BASE = p["BASE"]
    MANTLE = p["MANTLE"]
    SURFACE0 = p["SURFACE0"]
    SURFACE1 = p["SURFACE1"]
    SURFACE2 = p["SURFACE2"]
    OVERLAY0 = p["OVERLAY0"]
    SUBTEXT0 = p["SUBTEXT0"]
    TEXT = p["TEXT"]
    BLUE = p["BLUE"]
    GREEN = p["GREEN"]
    PEACH = p["PEACH"]
    TEAL = p["TEAL"]
    RED = p["RED"]
    MAUVE = p["MAUVE"]
    YELLOW = p["YELLOW"]
    SECTION_COLORS = [BLUE, GREEN, PEACH, MAUVE, RED, TEAL, YELLOW]
    QSS = _build_qss()
    _save_setting("theme", name)
    for cb in _on_change_callbacks:
        try:
            cb()
        except Exception:
            pass


def _build_qss() -> str:
    return f"""
QMainWindow, QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-family: sans-serif;
    font-size: 13px;
}}

QLabel {{
    color: {TEXT};
}}

QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {SURFACE1};
}}
QPushButton:pressed {{
    background-color: {SURFACE2};
}}
QPushButton:disabled {{
    color: {SURFACE1};
    background-color: {SURFACE0};
}}

QPushButton[accent="true"] {{
    background-color: {BLUE};
    color: {BASE};
}}
QPushButton[accent="true"]:hover {{
    background-color: {SURFACE1};
}}

QComboBox {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: none;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    min-width: 120px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    selection-background-color: {SURFACE0};
    outline: none;
}}

QListWidget {{
    background-color: {BASE};
    border: none;
    outline: none;
}}
QListWidget::item {{
    background-color: {MANTLE};
    border: none;
    padding: 8px;
    border-radius: 4px;
    margin: 1px 0px;
}}
QListWidget::item:alternate {{
    background-color: {BASE};
}}
QListWidget::item:selected {{
    background-color: {SURFACE0};
}}
QListWidget::item:hover {{
    background-color: {SURFACE0};
}}

QSlider::groove:horizontal {{
    background: {SURFACE1};
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {TEXT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {BLUE};
    border-radius: 3px;
}}

QTextEdit {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 8px;
    font-size: 13px;
    selection-background-color: {SURFACE0};
}}
QTextEdit:focus {{
    border-color: {BLUE};
}}

QScrollBar:vertical {{
    background: {BASE};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {SURFACE1};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {BASE};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {SURFACE1};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QLineEdit {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus {{
    border-color: {BLUE};
}}

QInputDialog {{
    background-color: {MANTLE};
}}

QMessageBox {{
    background-color: {MANTLE};
}}
QMessageBox QLabel {{
    color: {TEXT};
}}

QProgressBar {{
    background-color: {SURFACE0};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {BLUE};
    border-radius: 4px;
}}

QToolTip {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    padding: 4px;
    border-radius: 4px;
}}

QMenu {{
    background-color: {MANTLE};
    color: {TEXT};
    border: 1px solid {SURFACE0};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {SURFACE0};
}}

QSplitter::handle {{
    background-color: {SURFACE0};
    width: 2px;
}}
"""


# ── Settings persistence ────────────────────────────────

def _load_setting(key: str, default=None):
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
        return data.get(key, default)
    except Exception:
        return default


def _save_setting(key: str, value):
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(_SETTINGS_PATH.read_text())
        except Exception:
            data = {}
        data[key] = value
        _SETTINGS_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def load_saved_theme():
    name = _load_setting("theme", "Catppuccin Mocha")
    set_theme(name)


# Initialize on import
load_saved_theme()
