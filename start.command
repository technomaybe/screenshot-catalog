#!/usr/bin/env bash
# start.command — launch Screenshot Catalog in development mode
# Double-click in Finder, or run: bash start.command

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "$DIR/.venv" ]; then
  echo "Virtual environment not found. Running install first..."
  bash "$DIR/install.sh"
fi

echo "[setup] Installing any missing packages..."
"$DIR/.venv/bin/pip" install --quiet pywebview rumps

export SCREENSHOTS_DIR="${SCREENSHOTS_DIR:-$HOME/Dropbox/screenshots}"
export SCREENSHOT_DB_PATH="$DIR/screenshot_index.db"
export APP_PORT=5051

if [ ! -d "$SCREENSHOTS_DIR" ]; then
  echo "WARNING: Screenshots folder not found: $SCREENSHOTS_DIR"
fi

echo "Starting Screenshot Catalog..."
exec "$DIR/.venv/bin/python3" "$DIR/main.py"
