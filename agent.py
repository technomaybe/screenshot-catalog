"""
Screenshot Cataloging Agent
===========================
Watches SCREENSHOTS_DIR for new image files, extracts text via OCR,
and stores results in a local SQLite database for full-text search.

Usage:
    python agent.py              # Watch for new files (runs until Ctrl+C)
    python agent.py --scan       # One-time scan of all existing files, then watch
    python agent.py --scan-only  # One-time scan only (no watching)
"""

import os
import sys
import time
import argparse
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import db
import ocr
from config import SCREENSHOTS_DIR, SUPPORTED_EXTENSIONS
from app_logging import get_logger

log = get_logger("agent")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_file(file_path: str):
    """OCR a single image and insert into the database. Skips duplicates."""
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return

    if db.is_already_indexed(file_path):
        log.debug("Already indexed, skipping: %s", file_path)
        return

    hash_val = db.file_hash(file_path)
    if db.is_hash_indexed(hash_val):
        log.info("Duplicate content (hash match), skipping: %s", os.path.basename(file_path))
        # Still record the path so it's not re-checked
        db.insert_record(file_path, ocr_text="[duplicate]",
                         file_hash_val=hash_val, status="duplicate")
        return

    log.info("Processing: %s", os.path.basename(file_path))
    try:
        text = ocr.extract_text(file_path)
        db.insert_record(file_path, ocr_text=text, file_hash_val=hash_val, status="processed")
        preview = text[:80].replace("\n", " ") if text else "(no text found)"
        log.info("  Indexed (%d chars) — %s…", len(text), preview)
    except Exception as exc:
        log.error("  OCR failed for %s: %s", os.path.basename(file_path), exc)
        db.insert_record(file_path, ocr_text=None,
                         file_hash_val=hash_val, status="failed", error=str(exc))


# ---------------------------------------------------------------------------
# Bulk scan
# ---------------------------------------------------------------------------

def scan_existing(directory: str | None = None):
    """Walk the screenshots folder and process every image that isn't indexed yet.

    Pass ``directory`` to scan a specific folder (used by the in-process
    re-index trigger). Defaults to the folder configured at startup.
    """
    target = directory or SCREENSHOTS_DIR
    log.info("Scanning existing screenshots in: %s", target)
    total = 0
    for root, _, files in os.walk(target):
        for fname in sorted(files):
            if Path(fname).suffix.lower() in SUPPORTED_EXTENSIONS:
                process_file(os.path.join(root, fname))
                total += 1
    stats = db.get_stats()
    log.info(
        "Scan complete. Files seen: %d | DB total: %d | processed: %d | failed: %d",
        total, stats["total"], stats["processed"], stats["failed"],
    )


# ---------------------------------------------------------------------------
# File watcher
# ---------------------------------------------------------------------------

class ScreenshotHandler(FileSystemEventHandler):
    """React to new files appearing in the watch folder."""

    def on_created(self, event):
        if event.is_directory:
            return
        # Give the OS a moment to finish writing the file
        time.sleep(1)
        process_file(event.src_path)

    def on_moved(self, event):
        # Handles files moved/renamed into the folder
        if event.is_directory:
            return
        time.sleep(1)
        process_file(event.dest_path)


def watch():
    if not os.path.isdir(SCREENSHOTS_DIR):
        log.error("Screenshots directory not found: %s", SCREENSHOTS_DIR)
        sys.exit(1)

    handler = ScreenshotHandler()
    observer = Observer()
    observer.schedule(handler, SCREENSHOTS_DIR, recursive=True)
    observer.start()
    log.info("Watching for new screenshots in: %s", SCREENSHOTS_DIR)
    log.info("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        log.info("Stopping watcher…")
        observer.stop()
    observer.join()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(scan: bool = True, scan_only: bool = False):
    """Programmatic entry — call from a background thread in main.py."""
    db.initialize_db()
    log.info("Agent starting with screenshots dir: %s", SCREENSHOTS_DIR)
    if scan_only:
        scan_existing()
        return
    if scan:
        scan_existing()
    watch()


def main():
    parser = argparse.ArgumentParser(description="Screenshot cataloging agent")
    parser.add_argument("--scan", action="store_true",
                        help="Scan existing screenshots before watching")
    parser.add_argument("--scan-only", action="store_true",
                        help="Scan and exit (no watching)")
    args = parser.parse_args()
    run(scan=args.scan, scan_only=args.scan_only)


if __name__ == "__main__":
    main()
