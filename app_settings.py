import json
import os
import subprocess
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # A packaged .app's Contents/MacOS is inside the signed bundle itself —
    # writing there means every rebuild (which replaces the bundle
    # wholesale) silently wipes whatever the user configured in Settings.
    # Use the same user-writable Application Support directory main.py
    # already uses for the DB, so settings survive rebuilds.
    BASE_DIR = Path.home() / "Library" / "Application Support" / "SnappyOCR"
    BASE_DIR.mkdir(parents=True, exist_ok=True)
else:
    BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "app_settings.json"


def _macos_screenshot_location() -> str:
    """Wherever the *native* macOS screenshot tool (Cmd+Shift+3/4/5, or the
    Screenshot app) is currently configured to save to.

    That location is a user preference, not a fixed path — System Settings
    > Screenshot writes it to `com.apple.screencapture`'s "location" key,
    same as the Options menu in the Cmd+Shift+5 toolbar. Reading it here
    means a fresh install of SnappyOCR watches the same folder macOS
    already drops screenshots into, instead of guessing. If that
    preference was never set, macOS itself defaults to the Desktop.
    """
    try:
        result = subprocess.run(
            ["defaults", "read", "com.apple.screencapture", "location"],
            capture_output=True, text=True, timeout=5,
        )
        location = result.stdout.strip()
        if result.returncode == 0 and location:
            return os.path.expanduser(location)
    except Exception:
        pass
    return str(Path.home() / "Desktop")


_DEFAULT_SCREENSHOTS_DIR = (
    _macos_screenshot_location()
    if sys.platform == "darwin"
    else str(Path.home() / "Dropbox" / "screenshots")
)

DEFAULTS = {
    "SCREENSHOTS_DIR": _DEFAULT_SCREENSHOTS_DIR,
    "APP_PORT": 5051,
    "SHOW_MENU_BAR_ICON": True,
    "SCREENSHOT_DB_PATH": str(BASE_DIR / "screenshot_index.db"),
    "IMAGE_PATH_PREFIX_FROM": "",
    "IMAGE_PATH_PREFIX_TO": "",
    "EXPORT_ROOT": str(Path.home() / "ScreenshotCatalogExport"),
    "COLLEAGUE_SCREENSHOTS_DIR": str(Path.home() / "Pictures" / "Screenshots"),

    # SnappyOCR capture engine
    "CAPTURE_SAVE_DIR": "",           # blank -> falls back to SCREENSHOTS_DIR
    "HOTKEY_FULLSCREEN": "cmd+ctrl+3",
    "HOTKEY_AREA": "cmd+ctrl+4",
    "COPY_TO_CLIPBOARD": True,
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
