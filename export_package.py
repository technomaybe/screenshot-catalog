import json
import os
import shutil
from pathlib import Path

from app_settings import load_settings
from app_logging import get_logger

logger = get_logger("export_package")
BASE_DIR = Path(__file__).resolve().parent

FILES_TO_COPY = [
    "agent.py",
    "app_logging.py",
    "app_settings.py",
    "CANONICAL_SUMMARY.md",
    "config.py",
    "db.py",
    "export_package.py",
    "launch_web_app.ps1",
    "LICENSE",
    "ocr.py",
    "requirements.txt",
    "run_web_app.bat",
    "search.py",
    "screenshot_index.db",
    "web_app.py",
    "build_exe.bat",
    "start_for_colleague_template.bat",
    "README.md",
]

DIRS_TO_COPY = [
    "templates",
    "static",
]


def _write_export_settings(export_root: Path, settings: dict):
    colleague_dir = settings["COLLEAGUE_SCREENSHOTS_DIR"]
    export_settings = {
        "SCREENSHOTS_DIR": colleague_dir,
        "APP_PORT": int(settings["APP_PORT"]),
        "SCREENSHOT_DB_PATH": str(export_root / "screenshot_index.db"),
        "IMAGE_PATH_PREFIX_FROM": settings["SCREENSHOTS_DIR"],
        "IMAGE_PATH_PREFIX_TO": colleague_dir,
        "EXPORT_ROOT": str(export_root),
        "COLLEAGUE_SCREENSHOTS_DIR": colleague_dir,
    }
    (export_root / "app_settings.json").write_text(
        json.dumps(export_settings, indent=2),
        encoding="utf-8",
    )


def build_export_package():
    settings = load_settings()
    export_root = Path(settings["EXPORT_ROOT"])

    if export_root.exists():
        shutil.rmtree(export_root)
    export_root.mkdir(parents=True, exist_ok=True)

    for filename in FILES_TO_COPY:
        source = BASE_DIR / filename
        if source.exists():
            shutil.copy2(source, export_root / filename)

    _write_export_settings(export_root, settings)

    for dirname in DIRS_TO_COPY:
        source_dir = BASE_DIR / dirname
        target_dir = export_root / dirname
        if source_dir.exists():
            shutil.copytree(source_dir, target_dir)

    start_script = export_root / "start_for_colleague.bat"
    start_script.write_text(
        "@echo off\n"
        "setlocal\n"
        "cd /d \"%~dp0\"\n\n"
        "rem Update this to the screenshots folder available on the colleague machine.\n"
        f"set \"SCREENSHOTS_DIR={settings['COLLEAGUE_SCREENSHOTS_DIR']}\"\n"
        f"set \"IMAGE_PATH_PREFIX_FROM={settings['SCREENSHOTS_DIR']}\"\n"
        "set \"IMAGE_PATH_PREFIX_TO=%SCREENSHOTS_DIR%\"\n\n"
        "if /I \"%SCREENSHOTS_DIR%\"==\"C:\\Path\\To\\Copied\\Screenshots\" (\n"
        "  echo ERROR: Update SCREENSHOTS_DIR in start_for_colleague.bat before launching.\n"
        "  exit /b 1\n"
        ")\n\n"
        "if not exist \"%SCREENSHOTS_DIR%\" (\n"
        "  echo WARNING: SCREENSHOTS_DIR does not exist on this machine:\n"
        "  echo   %SCREENSHOTS_DIR%\n"
        "  echo Image previews may fail until this path is corrected.\n"
        ")\n\n"
        f"if \"%APP_PORT%\"==\"\" set APP_PORT={settings['APP_PORT']}\n"
        "call \"%~dp0run_web_app.bat\"\n\n"
        "endlocal\n",
        encoding="utf-8",
    )

    logger.info("Share package created at %s", export_root)
    return export_root


if __name__ == "__main__":
    path = build_export_package()
    print(f"Share package created at: {path}")
