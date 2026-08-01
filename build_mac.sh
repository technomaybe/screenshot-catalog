#!/usr/bin/env bash
# build_mac.sh — build Screenshot Catalog.app for macOS
# Run from the project root:  bash build_mac.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

VENV="$DIR/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"
DIST="$DIR/dist"
APP_NAME="Screenshot Catalog"

echo "=== Screenshot Catalog — macOS App Build ==="
echo ""

# ── 1. Virtual environment ────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "[1/6] Creating virtual environment..."
  python3.11 -m venv "$VENV" 2>/dev/null || python3 -m venv "$VENV"
else
  echo "[1/6] Virtual environment found ✓"
fi

# ── 2. Dependencies ───────────────────────────────────────────────────────────
echo "[2/6] Installing dependencies..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$DIR/requirements.txt" --quiet
"$PIP" install pyinstaller pywebview --quiet

# ── 3. Convert logo to ICNS ──────────────────────────────────────────────────
echo "[3/6] Creating app icon (ICNS)..."
ICONSET="$DIR/ScreenshotCatalog.iconset"
rm -rf "$ICONSET"
mkdir "$ICONSET"

LOGO="$DIR/logo-v2.png"
for SIZE in 16 32 64 128 256 512; do
  sips -z $SIZE $SIZE "$LOGO" --out "$ICONSET/icon_${SIZE}x${SIZE}.png"     &>/dev/null
  DOUBLE=$((SIZE * 2))
  sips -z $DOUBLE $DOUBLE "$LOGO" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" &>/dev/null
done
iconutil -c icns "$ICONSET" -o "$DIR/ScreenshotCatalog.icns"
rm -rf "$ICONSET"
echo "    Icon created ✓"

# ── 4. PyInstaller ────────────────────────────────────────────────────────────
echo "[4/6] Running PyInstaller..."
rm -rf "$DIR/build" "$DIST"
"$VENV/bin/pyinstaller" \
  --clean \
  --noconfirm \
  "$DIR/ScreenshotCatalog.spec"

# ── 5. Verify ────────────────────────────────────────────────────────────────
APP_PATH="$DIST/$APP_NAME.app"
if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: Build failed — $APP_PATH not found"
  exit 1
fi
echo "[5/6] Build succeeded ✓"
echo "    $APP_PATH"

# ── 6. First-run note ────────────────────────────────────────────────────────
echo ""
echo "[6/6] Done!"
echo ""
echo "To install:"
echo "  cp -R \"$APP_PATH\" /Applications/"
echo ""
echo "First launch — macOS Gatekeeper will block it because the app is unsigned."
echo "Right-click → Open → Open to bypass (one time only)."
echo ""
echo "Tesseract must be installed on the machine (brew install tesseract)."
