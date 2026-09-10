#!/usr/bin/env bash
# build_mac.sh — build SnappyOCR.app for macOS
# Run from the project root:  bash build_mac.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

VENV="$DIR/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"
DIST="$DIR/dist"
APP_NAME="SnappyOCR"

echo "=== SnappyOCR — macOS App Build ==="
echo ""

# ── 0. Clean filesystem detritus ──────────────────────────────────────────────
# Cloud-synced folders (this project lives under ~/Documents, likely iCloud
# Drive) tend to accumulate .DS_Store files and AppleDouble sidecar files
# (._something) that codesign refuses to sign a bundle containing. Clean the
# source dirs PyInstaller copies from, so they never make it into the app.
find "$DIR/templates" "$DIR/static" \( -name ".DS_Store" -o -name "._*" \) -delete 2>/dev/null || true

# ── 1. Virtual environment ────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "[1/7] Creating virtual environment..."
  python3.11 -m venv "$VENV" 2>/dev/null || python3 -m venv "$VENV"
else
  echo "[1/7] Virtual environment found ✓"
fi

# ── 2. Dependencies ───────────────────────────────────────────────────────────
echo "[2/7] Installing dependencies..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$DIR/requirements.txt" --quiet
"$PIP" install pyinstaller pywebview --quiet

# ── 3. Convert logo to ICNS ──────────────────────────────────────────────────
echo "[3/7] Creating app icon (ICNS)..."
ICONSET="$DIR/SnappyOCR.iconset"
rm -rf "$ICONSET"
mkdir "$ICONSET"

LOGO="$DIR/logo-v2.png"
for SIZE in 16 32 64 128 256 512; do
  sips -z $SIZE $SIZE "$LOGO" --out "$ICONSET/icon_${SIZE}x${SIZE}.png"     &>/dev/null
  DOUBLE=$((SIZE * 2))
  sips -z $DOUBLE $DOUBLE "$LOGO" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" &>/dev/null
done
iconutil -c icns "$ICONSET" -o "$DIR/SnappyOCR.icns"
rm -rf "$ICONSET"
echo "    Icon created ✓"

# ── 4. PyInstaller ────────────────────────────────────────────────────────────
echo "[4/7] Running PyInstaller..."
rm -rf "$DIR/build" "$DIST"
"$VENV/bin/pyinstaller" \
  --clean \
  --noconfirm \
  "$DIR/SnappyOCR.spec"

# ── 5. Verify ────────────────────────────────────────────────────────────────
APP_PATH="$DIST/$APP_NAME.app"
if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: Build failed — $APP_PATH not found"
  exit 1
fi
echo "[5/7] Build succeeded ✓"
echo "    $APP_PATH"

# ── 6. Code signing ───────────────────────────────────────────────────────────
# PyInstaller leaves the app unsigned (see SnappyOCR.spec: codesign_identity=
# None). An unsigned/ad-hoc identity changes on every rebuild, which makes
# macOS TCC treat each rebuild as a brand-new app and silently drop
# previously granted Screen Recording / Accessibility permissions — captures
# then fail with no visible error. Signing with a STABLE local identity
# fixes that: run `bash setup_codesign.sh` once per Mac to create it.
CODESIGN_IDENTITY="SnappyOCR Local Dev 2"
echo "[6/7] Code signing..."
find "$APP_PATH" \( -name ".DS_Store" -o -name "._*" \) -delete 2>/dev/null || true
# Stripping com.apple.FinderInfo in place (xattr -c, xattr -d, even a
# ditto --norsrc clean-copy) never stuck on Python.framework or the .app
# itself -- it kept coming right back by the time codesign walked the tree
# a few seconds later. Most likely cause: this project folder lives under
# ~/Documents, which is commonly iCloud-synced and actively watched by
# Spotlight/Finder daemons that re-tag bundle-type directories (.app,
# .framework) with metadata on their own schedule -- a losing race against
# any in-place cleanup. Sidestep it: move the whole built app out to a
# private tmp directory (not synced, not indexed the same way) for the
# actual signing, then move the signed result back.
TMP_SIGN_DIR="$(mktemp -d)"
TMP_APP_PATH="$TMP_SIGN_DIR/$APP_NAME.app"
mv "$APP_PATH" "$TMP_APP_PATH"
find "$TMP_APP_PATH" -exec xattr -c {} \; 2>/dev/null || true
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CODESIGN_IDENTITY"; then
  codesign --force --sign "$CODESIGN_IDENTITY" "$TMP_APP_PATH"
  codesign --verify --verbose "$TMP_APP_PATH" 2>&1 | sed 's/^/    /'
  echo "    Signed with '$CODESIGN_IDENTITY' ✓ (permissions will survive future rebuilds)"
else
  echo "    Skipped — no '$CODESIGN_IDENTITY' certificate found."
  echo "    Run 'bash setup_codesign.sh' once, then rebuild, so Screen Recording /"
  echo "    Accessibility permissions survive future rebuilds instead of resetting."
fi
mv "$TMP_APP_PATH" "$APP_PATH"
rm -rf "$TMP_SIGN_DIR" 2>/dev/null || true

# ── 7. First-run note ────────────────────────────────────────────────────────
echo ""
echo "[7/7] Done!"
echo ""
echo "To install:"
echo "  cp -R \"$APP_PATH\" /Applications/"
echo ""
echo "First launch — macOS Gatekeeper will still warn because this isn't a"
echo "Developer ID (Apple-notarized) signature, just a local one."
echo "Right-click → Open → Open to bypass (one time only)."
echo ""
echo "Tesseract must be installed on the machine (brew install tesseract)."
