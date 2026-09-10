# SnappyOCR

**A native macOS menu-bar app that captures your screen and makes every capture searchable — in one app.** Hit a hotkey to grab the full screen or a hand-picked area (with a live crosshair cursor), the image lands wherever you want it, gets copied to your clipboard automatically, and is OCR'd in the background so you can find it later by the text inside it.

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white)
![OCR](https://img.shields.io/badge/OCR-Tesseract-5c6bc0?style=flat-square)

---

## The problem

Screenshots pile up by the thousands and become impossible to find — you remember the *content* but not the filename or date. macOS won't search the text *inside* an image. And the built-in screenshot tool doesn't put the file where you want it, copy it to your clipboard, or make it searchable on its own.

## The fix

SnappyOCR solves the whole loop in one app:

- **Custom capture hotkeys** — configurable global shortcuts for full-screen capture and interactive area selection, with macOS's own crosshair/reticle cursor and live pixel-dimension readout while you drag.
- **Goes exactly where you want it** — pick a custom save folder (defaults to the watched Screenshots folder, so it's searchable immediately).
- **Clipboard, automatically** — every capture is copied to the clipboard the moment it's taken; just Cmd+V.
- **Auto-OCR** — a watchdog monitors the save folder and OCRs every new image the moment it lands, via Tesseract.
- **Full-text search** — extracted text goes into a local database so you can search captures by what they *say*.
- **Native menu-bar UX** — lives quietly in the macOS menu bar (NSStatusItem); the UI is a local Flask app rendered in a native WebView window.
- **Ships as a real app** — packaged into a double-clickable `.app` bundle with PyInstaller.

## How it's built

```
main.py            →  unified entry point (dev + packaged .app)
  ├── Flask server        — background daemon thread (local web UI + API)
  ├── OCR agent           — background daemon thread (watchdog + Tesseract)
  ├── capture engine       — global hotkeys + screencapture + clipboard
  ├── pywebview window     — native WKWebView, main thread
  └── NSStatusItem         — menu-bar icon (rumps)

capture.py         →  global hotkeys, screencapture wrapper, clipboard
db.py              →  SQLite storage + full-text search
ocr.py             →  image → text pipeline
build_mac.sh       →  one-command build to a distributable .app
```

User data (database, settings, logs) is stored under `~/Library/Application Support/SnappyOCR` — never inside the app bundle — so updates never wipe your catalog. (Upgrading from the earlier "Screenshot Catalog" name migrates that data automatically on first launch.)

## Tech stack

| Concern | Tooling |
|---|---|
| Screen capture | macOS's built-in `/usr/sbin/screencapture` (full-screen + interactive `-i` area select) |
| Global hotkeys | `NSEvent` global/local monitors (pyobjc/AppKit) |
| Clipboard | `NSPasteboard` |
| OCR | pytesseract (Tesseract) + Pillow |
| File watching | watchdog |
| Local server / UI | Flask + pywebview (WKWebView) |
| Menu bar | rumps / NSStatusItem |
| Packaging | PyInstaller |

## Permissions

SnappyOCR needs two macOS permissions, both requested automatically the first time they're needed:

- **Accessibility** (System Settings → Privacy & Security → Accessibility) — required for global capture hotkeys to fire while another app is frontmost.
- **Screen Recording** (System Settings → Privacy & Security → Screen Recording) — required to capture pixels off the screen at all.

If a hotkey doesn't seem to do anything, check that SnappyOCR is enabled in both lists.

## Build & run

```bash
git clone https://github.com/technomaybe/screenshot-catalog.git && cd screenshot-catalog && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
python main.py          # run in development
bash build_mac.sh       # build the distributable SnappyOCR.app
```

> Requires Tesseract (`brew install tesseract`).

Default capture hotkeys are **⌘⌃3** (full screen) and **⌘⌃4** (area) — chosen to avoid colliding with macOS's own ⌘⇧3/4/5. Change them any time in Settings.

---

*Built by Patrick Schroeder.*
