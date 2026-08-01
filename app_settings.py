import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "app_settings.json"

DEFAULTS = {
    "SCREENSHOTS_DIR": str(Path.home() / "Dropbox" / "screenshots"),
    "APP_PORT": 5051,
    "SHOW_MENU_BAR_ICON": True,
    "SCREENSHOT_DB_PATH": str(BASE_DIR / "screenshot_index.db"),
    "IMAGE_PATH_PREFIX_FROM": "",
    "IMAGE_PATH_PREFIX_TO": "",
    "EXPORT_ROOT": str(Path.home() / "ScreenshotCatalogExport"),
    "COLLEAGUE_SCREENSHOTS_DIR": str(Path.home() / "Pictures" / "Screenshots"),
}


def load_settings():
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update({k: v for k, v in loaded.items() if v not in (None, "")})
        except Exception:
            pass
    return settings


def save_settings(new_values: dict):
    settings = load_settings()
    settings.update(new_values)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings
