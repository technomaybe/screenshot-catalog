import os
import sys
from app_settings import load_settings

SETTINGS = load_settings()

# ---------------------------------------------------------------------------
# Screenshots directory
# Override by setting the SCREENSHOTS_DIR environment variable, e.g.:
#   export SCREENSHOTS_DIR=/mnt/screenshots      (Ubuntu, SMB mount)
#   set SCREENSHOTS_DIR=\\HOST\share\Screenshots  (Windows UNC path)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    _DEFAULT_SCREENSHOTS_DIR = SETTINGS["SCREENSHOTS_DIR"]
elif sys.platform == "darwin":
    # macOS default: ~/Pictures/Screenshots (where macOS saves Cmd+Shift+3/4)
    _DEFAULT_SCREENSHOTS_DIR = os.path.expanduser(
        SETTINGS.get("SCREENSHOTS_DIR", "~/Pictures/Screenshots")
    )
else:
    _DEFAULT_SCREENSHOTS_DIR = SETTINGS.get("SCREENSHOTS_DIR", "/mnt/screenshots")

SCREENSHOTS_DIR = os.environ.get("SCREENSHOTS_DIR", _DEFAULT_SCREENSHOTS_DIR)

# When a copied database contains original absolute paths from another machine,
# remap that original root to the colleague's local screenshots folder.
IMAGE_PATH_PREFIX_FROM = os.environ.get("IMAGE_PATH_PREFIX_FROM", SETTINGS["IMAGE_PATH_PREFIX_FROM"])
IMAGE_PATH_PREFIX_TO = os.environ.get("IMAGE_PATH_PREFIX_TO", SETTINGS["IMAGE_PATH_PREFIX_TO"])

# Database file stored in the project folder
DB_PATH = os.environ.get(
    "SCREENSHOT_DB_PATH",
    SETTINGS["SCREENSHOT_DB_PATH"],
)

APP_PORT = int(os.environ.get("APP_PORT", str(SETTINGS["APP_PORT"])))
EXPORT_ROOT = os.environ.get("EXPORT_ROOT", SETTINGS["EXPORT_ROOT"])
COLLEAGUE_SCREENSHOTS_DIR = os.environ.get(
    "COLLEAGUE_SCREENSHOTS_DIR",
    SETTINGS["COLLEAGUE_SCREENSHOTS_DIR"],
)

# Supported image extensions
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}

# How many search results to show by default
DEFAULT_SEARCH_LIMIT = 10

# Snippet length (characters) shown around a search match
SNIPPET_LENGTH = 300

# Tesseract executable path — auto-detected by platform
# Ubuntu install:  sudo apt install tesseract-ocr
# Windows install: https://github.com/UB-Mannheim/tesseract/wiki
if sys.platform == "win32":
    # Check user-level install first (no admin), then system-wide
    _user_tess = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tesseract.exe")
    _system_tess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    _default_tess = _user_tess if os.path.exists(_user_tess) else _system_tess
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", _default_tess)
elif sys.platform == "darwin":
    # macOS: Homebrew installs to /opt/homebrew/bin (Apple Silicon) or /usr/local/bin (Intel)
    _brew_arm = "/opt/homebrew/bin/tesseract"
    _brew_intel = "/usr/local/bin/tesseract"
    _default_tess = _brew_arm if os.path.exists(_brew_arm) else _brew_intel
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", _default_tess)
else:
    # Linux: tesseract is normally on PATH
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", None)
