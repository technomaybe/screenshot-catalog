"""
menubar.py — macOS menu bar app for Screenshot Catalog
Spawns the agent and web server as subprocesses, shows status in the menu bar.

Usage: python3 menubar.py   (called automatically by start.command)
"""

import os
import sqlite3
import subprocess
import sys
import webbrowser
from pathlib import Path

import rumps
from PIL import Image as PilImage

DIR = Path(__file__).resolve().parent
PYTHON = str(DIR / ".venv" / "bin" / "python3")
PORT = int(os.environ.get("APP_PORT", "5051"))
DB_PATH = os.environ.get("SCREENSHOT_DB_PATH", str(DIR / "screenshot_index.db"))
SCREENSHOTS_DIR = os.environ.get(
    "SCREENSHOTS_DIR", str(Path.home() / "Dropbox" / "screenshots")
)


def _prepare_icon() -> str | None:
    """Resize logo-image.png for the menu bar and return the temp path.
    Use 32x32 so it looks sharp on Retina displays. Keep RGBA so macOS
    can composite it properly — do NOT use template mode with a coloured logo."""
    src = DIR / "logo-v2.png"
    if not src.exists():
        return None
    dest = DIR / "_menubar_icon.png"
    try:
        img = PilImage.open(src).convert("RGBA")
        img = img.resize((32, 32), PilImage.LANCZOS)
        img.save(dest, "PNG")
        return str(dest)
    except Exception:
        return None


def _db_stats() -> dict:
    """Return {total, processed, failed} from the DB, or zeros if unavailable."""
    try:
        con = sqlite3.connect(DB_PATH, timeout=2)
        cur = con.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status='processed' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) "
            "FROM screenshot_index"
        )
        row = cur.fetchone()
        con.close()
        return {
            "total":     int(row[0] or 0),
            "processed": int(row[1] or 0),
            "failed":    int(row[2] or 0),
        }
    except Exception:
        return {"total": 0, "processed": 0, "failed": 0}


class ScreenshotCatalogApp(rumps.App):
    def __init__(self):
        icon_path = _prepare_icon()
        super().__init__("Screenshot Catalog",
                         title="" if icon_path else "📷",
                         icon=icon_path,
                         template=False,
                         quit_button=None)

        self.open_item   = rumps.MenuItem("Open Screenshot Catalog", callback=self.open_browser)
        self.status_item = rumps.MenuItem("Indexed: starting…")
        self.status_item.set_callback(None)   # not clickable

        self.menu = [
            self.open_item,
            self.status_item,
            None,  # separator
            rumps.MenuItem("Quit Screenshot Catalog", callback=self.quit_app),
        ]

        self.agent_proc  = None
        self.webapp_proc = None
        self._start_processes()

        # Refresh the indexed count every 15 seconds
        rumps.Timer(self._refresh_status, 15).start()
        # Open browser once after 3 s (give the web app time to start)
        self._open_timer = rumps.Timer(self._initial_open, 3)
        self._open_timer.start()

    # ── Process management ────────────────────────────────────────────────────

    def _build_env(self):
        env = os.environ.copy()
        env["SCREENSHOTS_DIR"]    = SCREENSHOTS_DIR
        env["SCREENSHOT_DB_PATH"] = DB_PATH
        env["APP_PORT"]           = str(PORT)
        return env

    def _start_processes(self):
        env = self._build_env()
        self.agent_proc = subprocess.Popen(
            [PYTHON, str(DIR / "agent.py"), "--scan"],
            cwd=str(DIR), env=env,
        )
        self.webapp_proc = subprocess.Popen(
            [PYTHON, str(DIR / "web_app.py")],
            cwd=str(DIR), env=env,
        )

    def _stop_processes(self):
        for proc in (self.agent_proc, self.webapp_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    # ── Timer callbacks ───────────────────────────────────────────────────────

    def _initial_open(self, _):
        self._open_timer.stop()
        self._refresh_status(None)
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    def _refresh_status(self, _):
        stats = _db_stats()
        if stats["failed"]:
            self.status_item.title = (
                f"Indexed: {stats['processed']:,}  ⚠️ {stats['failed']} failed"
            )
        elif stats["total"] == 0:
            self.status_item.title = "Indexed: scanning…"
        else:
            self.status_item.title = f"Indexed: {stats['processed']:,} screenshots"

    # ── Menu actions ──────────────────────────────────────────────────────────

    def open_browser(self, _):
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    def quit_app(self, _):
        self._stop_processes()
        rumps.quit_application()


if __name__ == "__main__":
    ScreenshotCatalogApp().run()
