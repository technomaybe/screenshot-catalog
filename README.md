# Screenshot Catalog

**A native macOS menu-bar app that makes every screenshot you've ever taken searchable.** It watches your screenshots folder, runs OCR on each new image in the background, and lets you find any screenshot by the text inside it.

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white)
![OCR](https://img.shields.io/badge/OCR-Tesseract-5c6bc0?style=flat-square)

---

## The problem

Screenshots pile up by the thousands and become impossible to find — you remember the *content* but not the filename or date. macOS won't search the text *inside* an image.

## The fix

Screenshot Catalog solves it once, in the background:

- **Auto-OCR** — a watchdog monitors your screenshots folder and OCRs every new image the moment it lands, via Tesseract.
- **Full-text search** — extracted text goes into a local database so you can search screenshots by what they *say*.
- **Native menu-bar UX** — lives quietly in the macOS menu bar (NSStatusItem); the UI is a local Flask app rendered in a native WebView window.
- **Ships as a real app** — packaged into a signed, double-clickable `.app` bundle with PyInstaller.

## How it's built

```
main.py            →  unified entry point (dev + packaged .app)
  ├── Flask server        — background daemon thread (local web UI + API)
  ├── OCR agent           — background daemon thread (watchdog + Tesseract)
  ├── pywebview window     — native WKWebView, main thread
  └── NSStatusItem         — menu-bar icon (rumps)

db.py              →  SQLite storage + full-text search
ocr.py             →  image → text pipeline
build_mac.sh       →  one-command build to a distributable .app
```

User data (database, settings, logs) is stored under `~/Library/Application Support/ScreenshotCatalog` — never inside the app bundle — so updates never wipe your catalog.

## Tech stack

| Concern | Tooling |
|---|---|
| OCR | pytesseract (Tesseract) + Pillow |
| File watching | watchdog |
| Local server / UI | Flask + pywebview (WKWebView) |
| Menu bar | rumps (NSStatusItem) |
| Packaging | PyInstaller |

## Build & run

```bash
git clone https://github.com/technomaybe/screenshot-catalog.git && cd screenshot-catalog && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
python main.py          # run in development
bash build_mac.sh       # build the distributable Screenshot Catalog.app
```

> Requires Tesseract (`brew install tesseract`).

---

*Built by Patrick Schroeder.*
