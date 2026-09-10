"""
main.py — Screenshot Catalog for macOS
=======================================
Unified entry point for both development and the PyInstaller .app bundle.

Architecture:
  • Flask web server  — background daemon thread
  • OCR agent         — background daemon thread
  • pywebview window  — main thread (WKWebView, macOS native)
  • NSStatusItem      — menu bar icon, created after pywebview initialises
"""

import os
import sys
import socket
import threading
import time
from pathlib import Path

# ── Resolve paths ─────────────────────────────────────────────────────────────
# When frozen by PyInstaller, resources live in sys._MEIPASS.
FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR: Path = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent

# User-writable data (DB, settings, logs) — never inside the .app bundle.
_APP_SUPPORT = Path.home() / "Library" / "Application Support"
DATA_DIR: Path = (_APP_SUPPORT / "SnappyOCR") if FROZEN else BUNDLE_DIR

if FROZEN and not DATA_DIR.exists():
    # One-time migration: SnappyOCR is Screenshot Catalog's new name+capture
    # engine, not a new app — carry the existing catalog (DB, settings, logs)
    # over so renaming doesn't look like data loss.
    _old_data_dir = _APP_SUPPORT / "ScreenshotCatalog"
    if _old_data_dir.exists():
        import shutil
        shutil.copytree(_old_data_dir, DATA_DIR)

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Add bundle dir to sys.path so all project imports resolve correctly.
if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

# ── Environment — set BEFORE importing config / app_settings ─────────────────
# The screenshots folder must come from the user's SAVED settings, otherwise a
# hard-coded default here silently overrides whatever they chose in the UI.
from app_settings import load_settings as _load_settings

_saved = _load_settings()
_saved_dir = os.path.expanduser(
    str(_saved.get("SCREENSHOTS_DIR") or (Path.home() / "Dropbox" / "screenshots"))
)
os.environ["SCREENSHOTS_DIR"] = _saved_dir
os.environ.setdefault("SCREENSHOT_DB_PATH",
                       str(DATA_DIR / "screenshot_index.db"))
os.environ["APP_PORT"] = str(_saved.get("APP_PORT", 5051))

# Copy writable config files out of the bundle on first run.
if FROZEN:
    for fname in ("app_settings.json",):
        src = BUNDLE_DIR / fname
        dst = DATA_DIR / fname
        if src.exists() and not dst.exists():
            import shutil
            shutil.copy2(src, dst)
    # Make sure logs dir exists
    (DATA_DIR / "logs").mkdir(exist_ok=True)

# ── Imports (after path/env setup) ───────────────────────────────────────────
import webview                          # pywebview — must run on main thread

# pywebview's Cocoa backend unconditionally forces
# NSApplicationActivationPolicyRegular (webview/platforms/cocoa.py:
# `app.setActivationPolicy_(0)`, run as a BrowserView class-body statement
# the moment that module is imported). That silently overrides Info.plist's
# LSUIElement=True, which is why the packaged app shows a Dock icon and gets
# regular-app window/Space semantics despite being built as a menu-bar-only
# accessory app.
#
# `import webview` above does NOT trigger this on its own — pywebview's
# Cocoa backend is loaded lazily, only once `webview.start(gui="cocoa")`
# runs (webview/guilib.py's `initialize()`, called synchronously from
# inside `start()`, before any window exists — this must run before
# `webview.create_window()` too: Apple's own docs say the activation
# policy must be set before an app creates any windows, and empirically
# calling this later, from the `_after_start` callback after the window
# already exists, throws an uncaught NSInvalidArgumentException and
# crashes the whole app (confirmed via a real crash report). So this has
# to happen here, at the top, before `main()` ever calls
# `webview.create_window()`.
#
# Force the cocoa import now instead of waiting for `initialize()` to do
# it lazily, so its activation-policy call happens immediately and this
# override — which must win — runs right after it. Python caches the
# module, so `initialize()`'s later `import` is a no-op.
try:
    import webview.platforms.cocoa  # noqa: F401  (forces `setActivationPolicy_(0)` now)
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
except Exception:
    pass

import capture
import db
import agent as agent_module
from web_app import app as flask_app
from config import APP_PORT
from app_logging import get_logger

log = get_logger("main")
PORT = APP_PORT
URL  = f"http://127.0.0.1:{PORT}"


# ── Flask thread ──────────────────────────────────────────────────────────────

def _run_flask():
    db.initialize_db()
    flask_app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


# ── Agent thread ──────────────────────────────────────────────────────────────

def _run_agent():
    agent_module.run(scan=True, scan_only=False)


# ── Wait for Flask ─────────────────────────────────────────────────────────────

def _wait_for_flask(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


# ── Menu bar status item (NSStatusItem via pyobjc) ───────────────────────────

def _create_status_item(window):
    """
    Create a macOS menu bar icon.
    Called from the pywebview setup thread (after the run loop is active).
    pyobjc is already installed as a rumps dependency.
    """
    try:
        import AppKit
        import objc

        class _Delegate(AppKit.NSObject):
            """Minimal ObjC delegate for the status item menu."""

            @objc.python_method
            def set_window(self, w):
                self._window = w

            def openApp_(self, sender):
                if self._window:
                    self._window.show()

            def captureFullScreen_(self, sender):
                capture.trigger_fullscreen_async()

            def captureArea_(self, sender):
                capture.trigger_area_async()

            def quitApp_(self, sender):
                AppKit.NSApplication.sharedApplication().terminate_(None)

        delegate = _Delegate.alloc().init()
        delegate.set_window(window)

        status_bar  = AppKit.NSStatusBar.systemStatusBar()
        status_item = status_bar.statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )

        # Icon — try logo-v2.png first, fall back to text
        icon_path = BUNDLE_DIR / "logo-v2.png"
        if icon_path.exists():
            ns_img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon_path))
            ns_img.setSize_(AppKit.NSMakeSize(22, 22))
            status_item.button().setImage_(ns_img)
        else:
            status_item.button().setTitle_("📷")

        # Menu
        from app_settings import load_settings as _load_settings_for_menu
        _menu_settings = _load_settings_for_menu()

        menu = AppKit.NSMenu.alloc().init()

        open_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open SnappyOCR", "openApp:", ""
        )
        open_item.setTarget_(delegate)
        menu.addItem_(open_item)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        fullscreen_hotkey = _menu_settings.get("HOTKEY_FULLSCREEN", "cmd+ctrl+3")
        capture_full_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Capture Full Screen ({fullscreen_hotkey})", "captureFullScreen:", ""
        )
        capture_full_item.setTarget_(delegate)
        menu.addItem_(capture_full_item)

        area_hotkey = _menu_settings.get("HOTKEY_AREA", "cmd+ctrl+4")
        capture_area_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Capture Selected Area… ({area_hotkey})", "captureArea:", ""
        )
        capture_area_item.setTarget_(delegate)
        menu.addItem_(capture_area_item)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit SnappyOCR", "quitApp:", ""
        )
        quit_item.setTarget_(delegate)
        menu.addItem_(quit_item)

        status_item.setMenu_(menu)

        # Keep strong references — Python GC would delete these otherwise.
        _create_status_item._status_item = status_item
        _create_status_item._delegate    = delegate

    except Exception as exc:
        log.warning("Menu bar icon unavailable: %s", exc)


# ── pywebview setup callback ──────────────────────────────────────────────────

def _after_start(window):
    """
    Runs in a background thread created by pywebview after the GUI loop starts.
    Waits for Flask, then loads the URL and schedules the status item on the main thread.
    """
    if _wait_for_flask():
        window.load_url(URL)
    else:
        log.error("Flask did not become ready — check port %s", PORT)

    # Check user preference before creating the status item.
    from app_settings import load_settings
    if load_settings().get("SHOW_MENU_BAR_ICON", True):
        try:
            from Foundation import NSOperationQueue
            NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: _create_status_item(window)
            )
        except Exception as exc:
            log.warning("Could not dispatch status item to main thread: %s", exc)
            _create_status_item(window)

    # Global capture hotkeys — also needs the Cocoa run loop, so dispatch the
    # same way as the status item above.
    try:
        from Foundation import NSOperationQueue
        NSOperationQueue.mainQueue().addOperationWithBlock_(capture.start_hotkeys)
    except Exception as exc:
        log.warning("Could not dispatch hotkey registration to main thread: %s", exc)
        capture.start_hotkeys()


# ── JS bridge — native folder picker exposed to the web UI ───────────────────

class _JsApi:
    """Methods here are callable from the page as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def pick_folder(self):
        """Open a native macOS folder chooser; return the chosen path or None."""
        if self._window is None:
            return None
        try:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception as exc:
            log.warning("Folder picker failed: %s", exc)
            return None
        if result:
            # pywebview returns a tuple/list of selected paths.
            return result[0]
        return None

    def suspend_hotkeys(self):
        """Called from Settings the instant 'Record shortcut…' is clicked —
        stops the live global hotkeys from firing on whatever combo is
        being typed as its own replacement."""
        try:
            capture.suspend_hotkeys()
            return True
        except Exception as exc:
            log.warning("suspend_hotkeys failed: %s", exc)
            return False

    def resume_hotkeys(self):
        """Called once a new shortcut is captured (or Escape cancels), and
        as a page-load safety net in case a previous session left hotkeys
        suspended."""
        try:
            capture.resume_hotkeys()
            return True
        except Exception as exc:
            log.warning("resume_hotkeys failed: %s", exc)
            return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Daemon threads — they die automatically when the main thread (pywebview) exits.
    threading.Thread(target=_run_flask, daemon=True, name="flask").start()
    threading.Thread(target=_run_agent, daemon=True, name="agent").start()

    js_api = _JsApi()
    window = webview.create_window(
        title     = "SnappyOCR",
        url       = "about:blank",   # replaced by _after_start once Flask is ready
        width     = 1280,
        height    = 820,
        min_size  = (900, 600),
        text_select = True,
        js_api    = js_api,
    )
    js_api.set_window(window)

    # gui='cocoa' forces the native WKWebView backend on macOS.
    webview.start(_after_start, args=[window], gui="cocoa", debug=False)


if __name__ == "__main__":
    main()
