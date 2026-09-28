import json

from app_paths import settings_path

_SETTINGS_PATH = settings_path()


def load_setting(key: str, default=None):
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
        return data.get(key, default)
    except Exception:
        return default


def save_setting(key: str, value):
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
