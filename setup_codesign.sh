#!/usr/bin/env bash
# setup_codesign.sh — one-time setup of a stable local code-signing
# certificate for SnappyOCR.
#
# Why this exists: every time build_mac.sh rebuilds the app, PyInstaller
# leaves it either unsigned or ad-hoc signed. macOS's permission system
# (TCC) ties grants like Screen Recording and Accessibility to the app's
# code-signing identity — so an unstable identity means every rebuild
# looks like a brand-new app to macOS, and previously granted permissions
# silently stop applying (captures fail with no error, hotkeys stop firing).
#
# This script creates ONE self-signed "Code Signing" certificate in your
# login keychain and trusts it for that purpose. You only need to run this
# once per Mac. After that, build_mac.sh signs every build with it, so
# macOS always sees the same identity and your permissions survive rebuilds.
#
# Run it once:  bash setup_codesign.sh
set -e

IDENTITY="SnappyOCR Local Dev 2"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

echo "=== SnappyOCR — Code Signing Setup ==="
echo ""

if security find-identity -v -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "$IDENTITY"; then
  echo "Certificate '$IDENTITY' already exists in your login keychain — nothing to do."
  echo "(Delete it in Keychain Access first if you want to regenerate it.)"
  exit 0
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "[1/3] Generating a self-signed code-signing certificate..."
openssl req -x509 -newkey rsa:2048 \
  -keyout "$WORKDIR/key.pem" \
  -out "$WORKDIR/cert.pem" \
  -days 3650 -nodes \
  -subj "/CN=$IDENTITY" \
  -addext "extendedKeyUsage=codeSigning" \
  -addext "basicConstraints=critical,CA:true" \
  &>/dev/null

echo "[2/3] Importing it into your login keychain..."
# Modern OpenSSL (3.x, e.g. Homebrew's) defaults to AES-256/SHA-256 when it
# packages a cert+key into a .p12 file. Apple's own `security import` only
# understands the older 3DES/SHA-1 defaults, so it fails with a misleading
# "MAC verification failed (wrong password?)" error even when the password
# is correct. Force the old, Apple-compatible algorithms explicitly so this
# works regardless of which openssl build is first on PATH.
if ! openssl pkcs12 -export \
  -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg SHA1 \
  -out "$WORKDIR/cert.p12" \
  -inkey "$WORKDIR/key.pem" \
  -in "$WORKDIR/cert.pem" \
  -passout pass:snappyocr 2>"$WORKDIR/pkcs12.err"; then
  echo "    (legacy PBE flags not supported by this openssl — retrying with -legacy)"
  openssl pkcs12 -export -legacy \
    -out "$WORKDIR/cert.p12" \
    -inkey "$WORKDIR/key.pem" \
    -in "$WORKDIR/cert.pem" \
    -passout pass:snappyocr
fi

security import "$WORKDIR/cert.p12" \
  -k "$KEYCHAIN" \
  -P snappyocr \
  -T /usr/bin/codesign -T /usr/bin/security

echo "[3/3] Trusting it for code signing..."
security add-trusted-cert -d -r trustRoot -p codeSign -k "$KEYCHAIN" "$WORKDIR/cert.pem"

echo ""
echo "Done. Verifying..."
if security find-identity -v -p codesigning "$KEYCHAIN" 2>/dev/null | grep -q "$IDENTITY"; then
  echo "'$IDENTITY' is ready. Rebuild the app with:  bash build_mac.sh"
else
  echo "WARNING: could not confirm the identity was installed — check Keychain Access"
  echo "manually (search for '$IDENTITY') before rebuilding."
fi
