"""
capture.py — SnappyOCR screen-capture engine
=============================================
Adds real screen-capture behaviour on top of the existing OCR/search catalog:

  * Global hotkeys for "capture full screen" and "capture a selected area"
  * Interactive area selection using macOS's own screencapture crosshair
    (a live reticle cursor with a pixel-dimension readout — built into the OS)
  * Saves the image to a user-configurable folder
  * Copies the captured image straight to the system clipboard
  * Drops the file into the same folder the OCR agent already watches, so it
    becomes searchable within a couple of seconds with zero extra code here.

Concepts used here (see PROJECT_KNOWLEDGE_BASE.md for the full write-up):
  * CGEventTap — a low-level, system-wide keyboard event observer, used
    here instead of NSEvent's global/local monitors because those turned
    out to be unreliable across different macOS desktops/Spaces.
  * AXIsProcessTrustedWithOptions — the Accessibility permission gate that
    global keyboard monitoring requires on macOS.
  * CGPreflightScreenCaptureAccess / CGRequestScreenCaptureAccess — the
    Screen Recording permission gate for anything that reads pixels off
    the screen, including a subprocess we launch ourselves.
  * NSPasteboard — writing an image object to the system clipboard.
"""

import subprocess
import threading
import time
from pathlib import Path

import Quartz
from AppKit import (
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSImage,
    NSPasteboard,
)

from app_logging import get_logger
from app_settings import load_settings

log = get_logger("capture")

SCREENCAPTURE_BIN = "/usr/sbin/screencapture"

# macOS virtual keycodes (kVK_ANSI_*) — these identify a *physical* key
# position on a US keyboard layout, not the character it produces. That's
# why "3" is 20 and not, say, ord("3"). Covers the keys people actually
# pick for shortcuts (digits, letters, function keys).
_KEYCODES = {
    "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28,
    "9": 25, "0": 29,
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4, "i": 34,
    "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35, "q": 12,
    "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7, "y": 16, "z": 6,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

_MODIFIERS = {
    "cmd": NSEventModifierFlagCommand,
    "command": NSEventModifierFlagCommand,
    "ctrl": NSEventModifierFlagControl,
    "control": NSEventModifierFlagControl,
    "opt": NSEventModifierFlagOption,
    "option": NSEventModifierFlagOption,
    "alt": NSEventModifierFlagOption,
    "shift": NSEventModifierFlagShift,
}

# Only these bits matter when comparing an incoming key event's modifier
# flags — ignores noise bits macOS sets for things like Caps Lock or the
# Fn/Globe key, which would otherwise make an exact-match comparison flaky.
_RELEVANT_MASK = (
    NSEventModifierFlagCommand
    | NSEventModifierFlagControl
    | NSEventModifierFlagOption
    | NSEventModifierFlagShift
)

DEFAULT_HOTKEY_FULLSCREEN = "cmd+ctrl+3"
DEFAULT_HOTKEY_AREA = "cmd+ctrl+4"


def parse_hotkey(hotkey: str):
    """Turn a string like 'cmd+ctrl+3' into (modifier_mask, keycode).

    Returns None if the string is empty or contains a token we don't
    recognise, so a bad setting fails safe (hotkey just doesn't register)
    instead of crashing the app on launch.
    """
    if not hotkey:
        return None
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        return None
    mask = 0
    keycode = None
    for part in parts:
        if part in _MODIFIERS:
            mask |= _MODIFIERS[part]
        elif part in _KEYCODES:
            keycode = _KEYCODES[part]
        else:
            log.warning("Unrecognized hotkey token %r in %r", part, hotkey)
            return None
    if keycode is None:
        return None
    return mask, keycode


def _timestamped_filename() -> str:
    return time.strftime("SnappyOCR %Y-%m-%d at %I.%M.%S %p.png")


def _capture_save_dir() -> Path:
    """Where new captures get written.

    Defaults to the same SCREENSHOTS_DIR the OCR agent already watches, so a
    capture is searchable within seconds with no extra wiring. Set
    CAPTURE_SAVE_DIR in Settings to send captures somewhere else instead.
    """
    settings = load_settings()
    raw = settings.get("CAPTURE_SAVE_DIR") or settings.get("SCREENSHOTS_DIR")
    folder = Path(str(raw)).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def copy_image_to_clipboard(path: str) -> bool:
    """Write the image at ``path`` onto the system clipboard as an image
    object, so a plain Cmd+V into Mail/Slack/Preview/etc. pastes the
    picture (not a file reference)."""
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        log.warning("Could not load image for clipboard: %s", path)
        return False
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    return bool(pb.writeObjects_([image]))


def _run_screencapture(args) -> bool:
    """Run /usr/sbin/screencapture and log everything it tells us.

    screencapture fails *silently* from the caller's point of view — a
    denied Screen Recording permission, a cancelled interactive selection,
    and a genuine crash all just mean "no file appeared" unless we capture
    its stdout/stderr and exit code ourselves. This is what let us prove
    (via the app log) that a capture was failing before it ever reached the
    clipboard-copy code.
    """
    try:
        result = subprocess.run(
            [SCREENCAPTURE_BIN] + args,
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            log.info("screencapture stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            log.warning("screencapture stderr: %s", result.stderr.strip())
        if result.returncode != 0:
            log.warning("screencapture exited with code %s (args=%s)", result.returncode, args)
        return result.returncode == 0
    except Exception as exc:
        log.error("screencapture failed to launch: %s", exc)
        return False


def _copy_to_clipboard_on_main_thread(path: str):
    """Dispatch the actual clipboard write to the main thread.

    capture_fullscreen()/capture_area() run on a background thread (so a
    slow interactive selection never freezes the app's UI) — but NSImage +
    NSPasteboard are AppKit APIs, and calling them from a thread pyobjc
    never set up an autorelease pool for is a well-known way for the write
    to silently do nothing. main.py already dispatches its other AppKit
    work (the status item, hotkey registration) onto the main queue the
    same way; do the same here rather than calling it inline.
    """
    def _do_copy():
        if copy_image_to_clipboard(path):
            log.info("Copied capture to clipboard: %s", Path(path).name)
        else:
            log.warning("Failed to copy capture to clipboard: %s", Path(path).name)

    try:
        from Foundation import NSOperationQueue
        NSOperationQueue.mainQueue().addOperationWithBlock_(_do_copy)
    except Exception as exc:
        log.warning("Could not dispatch clipboard copy to main thread (%s) — "
                    "copying inline instead", exc)
        _do_copy()


def _finish_capture(dest: Path):
    if not dest.exists():
        # Either the user pressed Escape during an area selection, or
        # screencapture itself failed (e.g. Screen Recording permission
        # not yet granted) — either way, there's nothing to do.
        log.info("Capture produced no file (cancelled or failed): %s", dest.name)
        return
    settings = load_settings()
    if settings.get("COPY_TO_CLIPBOARD", True):
        _copy_to_clipboard_on_main_thread(str(dest))
    else:
        log.info("Captured: %s", dest.name)


def capture_fullscreen():
    """Capture the whole screen immediately — no interaction required."""
    dest = _capture_save_dir() / _timestamped_filename()
    log.info("Capturing full screen -> %s", dest)
    _run_screencapture(["-x", str(dest)])   # -x = no camera-shutter sound
    _finish_capture(dest)


def capture_area():
    """Interactive area capture.

    Blocks (in whatever thread calls it) until the user drags a selection —
    macOS shows its own crosshair/reticle cursor with a live width x height
    readout — or cancels with Escape. Always call this off the main thread
    (see start_hotkeys/menu wiring below) so the app's own UI stays
    responsive while the user is dragging.
    """
    dest = _capture_save_dir() / _timestamped_filename()
    log.info("Capturing area -> %s", dest)
    _run_screencapture(["-i", "-x", str(dest)])
    _finish_capture(dest)


# Guards against launching two overlapping captures at once. Without this,
# a single hotkey press that somehow gets delivered twice (macOS key-repeat
# on a slightly-too-long press, or the global+local monitor pair both
# firing for the same event) spawns two concurrent `screencapture -i`
# processes. Two interactive selection overlays fighting over the screen at
# the same time is exactly what left a stray screencapture process stuck
# waiting for input on a later run — which looked like the hotkey simply
# stopped responding on the next press.
_capture_lock = threading.Lock()
_capture_in_progress = False


def _try_claim_capture_slot() -> bool:
    global _capture_in_progress
    with _capture_lock:
        if _capture_in_progress:
            return False
        _capture_in_progress = True
        return True


def _release_capture_slot():
    global _capture_in_progress
    with _capture_lock:
        _capture_in_progress = False


def trigger_fullscreen_async():
    if not _try_claim_capture_slot():
        log.info("Ignoring full-screen hotkey — a capture is already in progress")
        return

    def _run():
        try:
            capture_fullscreen()
        finally:
            _release_capture_slot()

    threading.Thread(target=_run, daemon=True, name="capture-fullscreen").start()


def trigger_area_async():
    if not _try_claim_capture_slot():
        log.info("Ignoring area-capture hotkey — a capture is already in progress")
        return

    def _run():
        try:
            capture_area()
        finally:
            _release_capture_slot()

    threading.Thread(target=_run, daemon=True, name="capture-area").start()


# ── Permissions ────────────────────────────────────────────────────────────

def ensure_accessibility_permission() -> bool:
    """Check — and, the first time, prompt for — the Accessibility
    permission that global keyboard monitoring requires (System Settings ->
    Privacy & Security -> Accessibility). Safe to call repeatedly."""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        from Foundation import NSDictionary

        options = NSDictionary.dictionaryWithObject_forKey_(
            True, kAXTrustedCheckOptionPrompt
        )
        trusted = bool(AXIsProcessTrustedWithOptions(options))
        if not trusted:
            log.warning(
                "Accessibility permission not yet granted — global hotkeys "
                "won't fire until SnappyOCR is enabled in System Settings > "
                "Privacy & Security > Accessibility."
            )
        return trusted
    except Exception as exc:
        log.warning("Could not check Accessibility permission: %s", exc)
        return False


def ensure_screen_recording_permission() -> bool:
    """Check — and, the first time, prompt for — the Screen Recording
    permission that capturing pixels off the screen requires."""
    try:
        import Quartz

        if Quartz.CGPreflightScreenCaptureAccess():
            return True
        log.warning(
            "Screen Recording permission not yet granted — requesting it "
            "now (a system prompt should appear)."
        )
        return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception as exc:
        log.warning("Could not check Screen Recording permission: %s", exc)
        return True  # don't block capture attempts on macOS versions without this API


# ── Global hotkeys ───────────────────────────────────────────────────────────
#
# Uses a single, low-level, system-wide CGEventTap rather than NSEvent's
# higher-level global/local monitor API. The NSEvent approach turned out to
# be unreliable specifically when triggered while a macOS desktop/Space
# other than whichever one SnappyOCR's own window last occupied was active
# -- the same hotkey sometimes fired and sometimes silently didn't,
# seemingly depending on which Space/app had focus at the moment. A
# CGEventTap at the session level is the technique virtually every
# professional macOS hotkey utility (BetterTouchTool, Karabiner-Elements,
# Rectangle, Alfred, etc.) uses specifically because it doesn't have that
# scoping gap: it observes keyboard events at the Window Server session
# level, independent of which app or Space is currently frontmost, rather
# than being filtered through any one app's own event-delivery pipeline.
# It still requires the same Accessibility permission NSEvent monitors did.

_event_tap = None          # the CGEventTap itself — a strong ref keeps it alive
_run_loop_source = None    # strong ref to the run-loop source added for it
_registered_hotkeys = {}   # (modifier_mask, keycode) -> action callable


def _event_tap_callback(proxy, event_type, event, refcon):
    # macOS disables a tap if its callback is ever too slow, or (more
    # rarely) if the user does something that makes it suspicious of the
    # tap. Re-enabling immediately is the standard, expected response --
    # without it, a hotkey that worked fine for a while could just go
    # silent for the rest of the session with nothing in our own log to
    # explain why.
    if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
        log.warning("Hotkey event tap was disabled by the system (reason=%s) — re-enabling", event_type)
        if _event_tap is not None:
            Quartz.CGEventTapEnable(_event_tap, True)
        return event

    if event_type != Quartz.kCGEventKeyDown:
        return event

    try:
        is_repeat = bool(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat))
    except Exception:
        is_repeat = False
    if is_repeat:
        return event

    keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
    flags = Quartz.CGEventGetFlags(event) & _RELEVANT_MASK

    # Snapshot with list() -- settings can be reloaded (resume_hotkeys)
    # from a different thread while this callback is running.
    for (mask, hk_keycode), action in list(_registered_hotkeys.items()):
        if keycode == hk_keycode and flags == mask:
            action()
            break

    return event


def _register_from_settings():
    """(Re)read the configured hotkeys from settings into _registered_hotkeys.

    Doesn't touch the event tap itself -- just what the callback matches
    against -- so this is safe to call at any time, including while the tap
    is live and running.
    """
    global _registered_hotkeys
    settings = load_settings()
    fullscreen_setting = settings.get("HOTKEY_FULLSCREEN", DEFAULT_HOTKEY_FULLSCREEN)
    area_setting = settings.get("HOTKEY_AREA", DEFAULT_HOTKEY_AREA)

    new_hotkeys = {}

    fullscreen_hk = parse_hotkey(fullscreen_setting)
    if fullscreen_hk:
        new_hotkeys[fullscreen_hk] = trigger_fullscreen_async
        log.info("Registered full-screen hotkey: %s", fullscreen_setting)
    else:
        log.warning("Full-screen hotkey not registered (invalid): %r", fullscreen_setting)

    area_hk = parse_hotkey(area_setting)
    if area_hk:
        new_hotkeys[area_hk] = trigger_area_async
        log.info("Registered area-capture hotkey: %s", area_setting)
    else:
        log.warning("Area-capture hotkey not registered (invalid): %r", area_setting)

    _registered_hotkeys = new_hotkeys


def _ensure_event_tap() -> bool:
    """Create the single system-wide event tap, if it doesn't exist yet.

    Must be called from a thread whose CFRunLoop is actually being pumped
    (the main thread, once pywebview/Cocoa's run loop is active) --
    CFRunLoopAddSource needs a running loop on THIS thread to ever fire.
    """
    global _event_tap, _run_loop_source
    if _event_tap is not None:
        return True

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        _event_tap_callback,
        None,
    )
    if tap is None:
        log.error(
            "Could not create the hotkey event tap — this usually means "
            "Accessibility permission isn't actually granted yet. Enable "
            "SnappyOCR in System Settings > Privacy & Security > "
            "Accessibility, then restart the app."
        )
        return False

    run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), run_loop_source, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    _event_tap = tap
    _run_loop_source = run_loop_source
    return True


def start_hotkeys():
    """Register the configured global hotkeys.

    Call once, after the Cocoa run loop is active (e.g. from pywebview's
    start callback in main.py, dispatched onto the main thread) — see
    _ensure_event_tap()'s docstring for why that matters here.
    """
    ensure_accessibility_permission()
    ensure_screen_recording_permission()
    if _ensure_event_tap():
        _register_from_settings()


def suspend_hotkeys():
    """Temporarily stop the event tap from firing (it stays installed).

    Without this, typing a *replacement* shortcut in Settings can collide
    with the shortcut still live from before — e.g. recording a new area
    hotkey while cmd+ctrl+4 (the default) is still armed fires a real
    capture, including the screen-hijacking interactive selector, in the
    middle of typing. The Settings page calls this (via the pywebview JS
    bridge) the moment "Record shortcut…" is clicked, and resume_hotkeys()
    right after a combo is captured or cancelled.
    """
    if _event_tap is not None:
        Quartz.CGEventTapEnable(_event_tap, False)
    log.info("Hotkeys suspended")


def resume_hotkeys():
    """Re-read hotkeys from settings and re-enable the event tap.

    Safe to call even if nothing was suspended (e.g. as a page-load safety
    net), and safe to call before the tap has ever been created (it'll just
    create it).
    """
    _register_from_settings()
    if _event_tap is not None:
        Quartz.CGEventTapEnable(_event_tap, True)
    else:
        _ensure_event_tap()
    log.info("Hotkeys resumed")
