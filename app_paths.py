from pathlib import Path

from platformdirs import user_data_path


APP_NAME = "transcreve"


def app_data_dir() -> Path:
    root = Path(user_data_path(APP_NAME, appauthor=False, roaming=False))
    root.mkdir(parents=True, exist_ok=True)
    return root


def music_dir() -> Path:
    path = app_data_dir() / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stems_dir() -> Path:
    path = app_data_dir() / "stems"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    path = app_data_dir() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def database_path() -> Path:
    return app_data_dir() / "transcreve.db"
