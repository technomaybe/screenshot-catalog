import os
import secrets
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

import db
from app_logging import get_logger
from app_settings import load_settings, save_settings
from config import (
    APP_PORT,
    DB_PATH,
    DEFAULT_SEARCH_LIMIT,
    IMAGE_PATH_PREFIX_FROM,
    IMAGE_PATH_PREFIX_TO,
    SUPPORTED_EXTENSIONS,
)
from export_package import build_export_package

app = Flask(__name__)
logger = get_logger("web_app")


def _load_or_create_secret_key() -> bytes:
    """Persist a random Flask session-signing key next to the DB, instead of
    a hardcoded one shared by every install. Session cookies aren't used for
    auth here, but signing flash messages with a public key is still sloppy."""
    key_path = Path(DB_PATH).resolve().parent / ".flask_secret_key"
    try:
        existing = key_path.read_bytes()
        if existing:
            return existing
    except OSError:
        pass

    key = secrets.token_bytes(32)
    try:
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
    except OSError:
        logger.warning("Could not persist Flask secret key to %s; using an in-memory key", key_path)
    return key


app.secret_key = _load_or_create_secret_key()


def _is_same_origin(header_value: str) -> bool:
    netloc = urllib.parse.urlsplit(header_value).netloc
    return netloc == request.host


@app.before_request
def _block_cross_origin_writes():
    """Reject state-changing requests whose Origin/Referer isn't this app.

    This server binds to 127.0.0.1 with no authentication, which means any
    webpage open in the user's browser can otherwise submit a plain HTML
    form POST to it (browsers don't block cross-origin form submissions,
    only cross-origin *reads* of the response). Without this check, a
    malicious site could silently trigger a screen capture, wipe the OCR
    index, or rewrite settings just by having the user's browser visit it.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if source and not _is_same_origin(source):
        logger.warning("Blocked cross-origin %s to %s (source=%s)", request.method, request.path, source)
        abort(403, description="Cross-origin requests are not allowed")


def resolve_image_path(file_path: str) -> str | None:
    """Resolve a stored DB path to an actual file on disk for this machine."""
    normalized = os.path.normpath(file_path)
    if os.path.exists(normalized):
        return normalized

    source_root = os.path.normpath(IMAGE_PATH_PREFIX_FROM)
    target_root = os.path.normpath(IMAGE_PATH_PREFIX_TO)
    if source_root and target_root:
        source_root_cmp = os.path.normcase(source_root)
        normalized_cmp = os.path.normcase(normalized)
        if normalized_cmp == source_root_cmp or normalized_cmp.startswith(source_root_cmp + os.sep):
            relative = normalized[len(source_root):].lstrip("\\/")
            remapped = os.path.normpath(os.path.join(target_root, relative))
            if os.path.exists(remapped):
                return remapped

    return None


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    limit_raw = request.args.get("limit", str(DEFAULT_SEARCH_LIMIT)).strip()
    sort = request.args.get("sort", "relevance")
    if sort not in ("relevance", "recent"):
        sort = "relevance"

    try:
        limit = max(1, min(int(limit_raw), 100))
    except ValueError:
        limit = DEFAULT_SEARCH_LIMIT

    stats = db.get_stats()
    results = []
    error = None

    if query:
        try:
            results = db.search(query, limit=limit, sort=sort)
        except Exception as exc:
            error = str(exc)

    return render_template(
        "index.html",
        active_tab="search",
        current_port=APP_PORT,
        query=query,
        limit=limit,
        results=results,
        stats=stats,
        error=error,
    )


@app.route("/word-cloud")
@app.route("/wordcloud")
def word_cloud():
    max_words_raw = request.args.get("max_words", "120").strip()
    try:
        max_words = max(20, min(int(max_words_raw), 300))
    except ValueError:
        max_words = 120

    stats = db.get_stats()
    words = db.get_word_cloud_words(max_words=max_words, min_len=3)

    if words:
        counts = [count for _, count in words]
        min_count = min(counts)
        max_count = max(counts)
    else:
        min_count = 0
        max_count = 0

    cloud_items = []
    for word, count in words:
        if max_count == min_count:
            size = 22
        else:
            size = int(14 + (count - min_count) * (44 - 14) / (max_count - min_count))
        cloud_items.append({"word": word, "count": count, "size": size})

    return render_template(
        "word_cloud.html",
        active_tab="word-cloud",
        current_port=APP_PORT,
        stats=stats,
        cloud_items=cloud_items,
        max_words=max_words,
    )


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        port_raw = request.form.get("app_port", str(APP_PORT)).strip()
        try:
            new_port = int(port_raw) if port_raw else APP_PORT
            if not (1024 <= new_port <= 65535):
                raise ValueError("port out of range")
        except ValueError:
            flash(f"Invalid port {port_raw!r} — keeping {APP_PORT}.", "error")
            new_port = APP_PORT

        updated = {
            "SCREENSHOTS_DIR": request.form.get("screenshots_dir", "").strip(),
            "APP_PORT": new_port,
            "SHOW_MENU_BAR_ICON": request.form.get("show_menu_bar_icon") == "1",
            "CAPTURE_SAVE_DIR": request.form.get("capture_save_dir", "").strip(),
            "HOTKEY_FULLSCREEN": request.form.get("hotkey_fullscreen", "").strip() or "cmd+ctrl+3",
            "HOTKEY_AREA": request.form.get("hotkey_area", "").strip() or "cmd+ctrl+4",
            "COPY_TO_CLIPBOARD": request.form.get("copy_to_clipboard") == "1",
        }
        save_settings(updated)
        logger.info("Settings updated via UI")
        flash(
            "Settings saved. Restart the app if you changed the port or either hotkey.",
            "success",
        )
        return redirect(url_for("settings_page"))

    settings = load_settings()
    return render_template(
        "settings.html",
        active_tab="settings",
        current_port=APP_PORT,
        settings=settings,
        stats=db.get_stats(),
    )


@app.post("/capture/fullscreen")
def capture_fullscreen_route():
    import capture
    capture.trigger_fullscreen_async()
    flash("Capturing full screen…", "success")
    return redirect(request.referrer or url_for("settings_page"))


@app.post("/capture/area")
def capture_area_route():
    import capture
    capture.trigger_area_async()
    flash("Select an area to capture (crosshair cursor)…", "success")
    return redirect(request.referrer or url_for("settings_page"))


@app.route("/about")
def about_page():
    return render_template(
        "about.html",
        active_tab="about",
        current_port=APP_PORT,
        stats=db.get_stats(),
    )


# Guard so a second click can't launch overlapping scans, plus live progress
# state that the stats bar polls via /stats.json.
_scan_lock = threading.Lock()
_scan_running = False
_scan_mode = None          # "rebuild" | "reindex" | None
_scan_target_total = 0     # image files found in the folder for this scan


def _count_images(folder: str) -> int:
    """Count supported image files in the folder (denominator for progress)."""
    count = 0
    for _root, _dirs, files in os.walk(folder):
        for fname in files:
            if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTENSIONS:
                count += 1
    return count


def _launch_scan(folder: str, clear_first: bool) -> bool:
    """Start a background scan of ``folder``. Optionally wipe the index first
    (full rebuild). Returns False if a scan is already running.

    Runs in-process: the old code shelled out via ``sys.executable``, which in
    the packaged .app is the app binary (not Python), so the scan never ran.
    """
    global _scan_running, _scan_mode, _scan_target_total
    with _scan_lock:
        if _scan_running:
            return False
        _scan_running = True
        _scan_mode = "rebuild" if clear_first else "reindex"
        _scan_target_total = 0

    import agent

    def _job():
        global _scan_running, _scan_target_total
        try:
            _scan_target_total = _count_images(folder)
            if clear_first:
                logger.info("Clearing index for full rebuild")
                db.clear_index()
            agent.scan_existing(folder)
            logger.info("Scan completed for %s", folder)
        except Exception as exc:
            logger.exception("Scan failed: %s", exc)
        finally:
            _scan_running = False

    threading.Thread(target=_job, name="scan", daemon=True).start()
    return True


@app.get("/stats.json")
def stats_json():
    """Live stats for the auto-updating stats bar."""
    data = db.get_stats()
    data.update({
        "scanning": _scan_running,
        "mode": _scan_mode,
        "target_total": _scan_target_total,
    })
    return data


def _validated_folder():
    """Return the configured screenshots folder if it exists, else None."""
    settings = load_settings()
    folder = os.path.expanduser(str(settings.get("SCREENSHOTS_DIR", "")).strip())
    if not folder or not os.path.isdir(folder):
        return None, folder
    return folder, folder


@app.post("/reindex")
def reindex():
    """Scan the folder for new/changed screenshots (skips already-indexed)."""
    folder, raw = _validated_folder()
    logger.info("Reindex requested from UI for folder: %s", raw)
    if folder is None:
        flash(
            f"Screenshots folder not found: {raw or '(empty)'}. "
            "Pick a valid folder in Settings and save, then try again.",
            "error",
        )
        return redirect(request.referrer or url_for("index"))

    if _launch_scan(folder, clear_first=False):
        flash(
            "Re-index started. New screenshots are indexed as they finish "
            "processing — refresh this page to watch the counts update.",
            "success",
        )
    else:
        flash("A scan is already running. Refresh to see progress.", "success")
    return redirect(request.referrer or url_for("index"))


@app.post("/rebuild-index")
def rebuild_index():
    """Wipe the catalog and re-OCR every file with the current OCR pipeline."""
    folder, raw = _validated_folder()
    logger.info("Full rebuild requested from UI for folder: %s", raw)
    if folder is None:
        flash(
            f"Screenshots folder not found: {raw or '(empty)'}. "
            "Pick a valid folder in Settings and save, then try again.",
            "error",
        )
        return redirect(request.referrer or url_for("index"))

    if _launch_scan(folder, clear_first=True):
        flash(
            "Rebuild started. The catalog was cleared and every screenshot is "
            "being re-OCR'd — counts will climb from zero as files finish. "
            "This is slower than a normal re-index; refresh to watch progress.",
            "success",
        )
    else:
        flash("A scan is already running. Refresh to see progress.", "success")
    return redirect(request.referrer or url_for("index"))


@app.post("/retry-failed")
def retry_failed():
    """Delete only failed records and re-scan, so files that failed OCR
    (e.g. an oversized stitched screenshot) get retried against the
    current pipeline without re-OCR'ing the whole library."""
    folder, raw = _validated_folder()
    logger.info("Retry-failed requested from UI for folder: %s", raw)
    if folder is None:
        flash(
            f"Screenshots folder not found: {raw or '(empty)'}. "
            "Pick a valid folder in Settings and save, then try again.",
            "error",
        )
        return redirect(request.referrer or url_for("index"))

    stats_before = db.get_stats()
    failed_count = stats_before.get("failed", 0)
    db.clear_failed()

    if _launch_scan(folder, clear_first=False):
        flash(
            f"Retrying {failed_count} failed file(s) — refresh this page to "
            "watch the counts update.",
            "success",
        )
    else:
        flash("A scan is already running. Refresh to see progress.", "success")
    return redirect(request.referrer or url_for("settings_page"))


@app.post("/export-package")
def export_package_route():
    export_root = build_export_package()
    flash(f"Share package created at: {export_root}", "success")
    return redirect(request.referrer or url_for("settings_page"))


@app.route("/status-files")
def status_files():
    LABELS = {
        "total":     "All indexed files",
        "ocr":       "Files with OCR text",
        "no_text":   "No text found",
        "duplicate": "Duplicate files",
        "failed":    "Failed files",
        "today":     "Indexed today",
        "this_week": "Indexed this week",
    }
    filter_key = request.args.get("filter", "total")
    if filter_key not in LABELS:
        filter_key = "total"
    rows = db.get_files_by_filter(filter_key)
    stats = db.get_stats()
    return render_template(
        "status_files.html",
        active_tab="",
        current_port=APP_PORT,
        filter_key=filter_key,
        label=LABELS[filter_key],
        rows=rows,
        stats=stats,
    )


@app.route("/image")
def image_proxy():
    """Safely serve an image from a local absolute path stored in the DB."""
    file_path = request.args.get("path", "")
    if not file_path:
        abort(400, description="Missing image path")

    normalized = os.path.normpath(file_path)
    if not os.path.isabs(normalized):
        abort(400, description="Path must be absolute")
    if not db.path_exists_in_index(normalized):
        logger.warning("Blocked image request for non-indexed path: %s", normalized)
        abort(404, description="Image is not present in the screenshot index")

    resolved = resolve_image_path(normalized)
    if not resolved:
        logger.warning("Image not found on this machine: %s", normalized)
        abort(404, description="Image not found on this machine")

    ext = Path(resolved).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}:
        abort(400, description="Unsupported image format")

    return send_file(resolved)


@app.route("/open-preview")
def open_preview():
    """Open an indexed image in macOS Preview (or default viewer on other OS)."""
    file_path = request.args.get("path", "")
    if not file_path:
        abort(400, description="Missing path")
    normalized = os.path.normpath(file_path)
    if not db.path_exists_in_index(normalized):
        abort(404, description="Not in index")
    resolved = resolve_image_path(normalized)
    if not resolved:
        abort(404, description="File not found on disk")
    import subprocess, sys as _sys
    if _sys.platform == "darwin":
        subprocess.Popen(["open", resolved])
    else:
        subprocess.Popen(["xdg-open", resolved])
    # Return to the referring page (or home)
    return redirect(request.referrer or url_for("index"))


@app.route("/healthz")
def healthz():
    return {"status": "ok", "app": "screenshot-catalog", "port": request.host.split(":")[-1]}, 200


@app.template_filter("img_url")
def to_img_url(file_path: str) -> str:
    return url_for("image_proxy") + "?path=" + urllib.parse.quote(file_path)


def main():
    db.initialize_db()
    port = APP_PORT
    logger.info("Starting web app on http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
