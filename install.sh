#!/usr/bin/env bash
# install.sh — one-time setup for Screenshot Catalog on macOS
# Run once: bash install.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== Screenshot Catalog — macOS Setup ==="
echo ""

# 1. Check Homebrew
if ! command -v brew &>/dev/null; then
  echo "ERROR: Homebrew not found."
  echo "Install it first: https://brew.sh"
  echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  exit 1
fi
echo "[1/4] Homebrew found ✓"

# 2. Install Tesseract if missing
if ! command -v tesseract &>/dev/null && \
   [ ! -f /opt/homebrew/bin/tesseract ] && \
   [ ! -f /usr/local/bin/tesseract ]; then
  echo "[2/4] Installing Tesseract via Homebrew..."
  brew install tesseract
else
  echo "[2/4] Tesseract found ✓"
fi

# 3. Create Python virtual environment (prefer 3.11+)
if [ ! -d "$DIR/.venv" ]; then
  echo "[3/4] Creating virtual environment..."
  if command -v python3.11 &>/dev/null; then
    python3.11 -m venv "$DIR/.venv"
  elif command -v python3.12 &>/dev/null; then
    python3.12 -m venv "$DIR/.venv"
  else
    python3 -m venv "$DIR/.venv"
  fi
else
  echo "[3/4] Virtual environment exists ✓"
fi

# 4. Install Python dependencies
echo "[4/4] Installing Python dependencies..."
"$DIR/.venv/bin/pip" install --upgrade pip --quiet
"$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt" --quiet

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start the app, double-click start.command"
echo "Or run:  bash start.command"
