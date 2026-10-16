#!/usr/bin/env bash
# Fetch the pinned llama-server binary for desktop packaging.
#
# Places llama-server-<target-triple> (plus .exe on Windows) into
# tauri-shell/src-tauri/binaries/ so Tauri externalBin can bundle it.
# SHA256 is pinned per asset; the extracted binary is version-checked
# (build >= 11669, required for MiniCPM-V 4.7).
#
# Usage: scripts/fetch-llama-server.sh [target-triple]
#   (default: rustc host triple)
set -euo pipefail

BUILD="b11669"
MIN_BUILD=11669

# asset per rust target triple
BASE_URL="https://github.com/ggml-org/llama.cpp/releases/download/${BUILD}"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  TARGET="$(rustc -vV | awk '/^host:/ {print $2}')"
fi

case "$TARGET" in
  aarch64-apple-darwin) ENTRY="llama-${BUILD}-bin-macos-arm64.tar.gz|dbed55493d72bc1ba2babc8770d669c2289b5bc4ee9fb2a4dfc158d45b7d13fd" ;;
  x86_64-apple-darwin) ENTRY="llama-${BUILD}-bin-macos-x64.tar.gz|cab28238d78158109b48deb27b05d50e0dcef56275d2e76da9ca8281526c7532" ;;
  x86_64-pc-windows-msvc) ENTRY="llama-${BUILD}-bin-win-cpu-x64.zip|37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b" ;;
  *) echo "error: no pinned llama-server asset for target '$TARGET'" >&2; exit 1 ;;
esac
ASSET="${ENTRY%%|*}"
SHA="${ENTRY##*|}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# llama-server is dynamically linked (libggml/libllama dylibs on macOS, DLLs
# on Windows), so the whole build/bin directory ships together as a Tauri
# resource, next to the texada-backend sidecar.
RES_DIR="$ROOT/tauri-shell/src-tauri/resources/llama-server"
mkdir -p "$RES_DIR"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "downloading $ASSET (build $BUILD) for $TARGET"
curl -fsSL --retry 3 -o "$WORK/$ASSET" "$BASE_URL/$ASSET"

echo "verifying sha256"
SHA_PYTHON="$(command -v python || command -v python3)"
ACTUAL="$("$SHA_PYTHON" - "$WORK/$ASSET" <<'PYHASH'
import hashlib
import sys
with open(sys.argv[1], "rb") as source:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PYHASH
)"
if [ "$ACTUAL" != "$SHA" ]; then
  echo "error: sha256 mismatch for $ASSET" >&2
  echo "  expected: $SHA" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 1
fi

echo "extracting"
case "$ASSET" in
  *.tar.gz) tar -xzf "$WORK/$ASSET" -C "$WORK" ;;
  *.zip)    "$SHA_PYTHON" - "$WORK/$ASSET" "$WORK" <<'PYZIP'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PYZIP
            ;;
esac

BINARY="llama-server"
case "$TARGET" in *windows*) BINARY="llama-server.exe" ;; esac
SRC="$(find "$WORK" -type f -name "$BINARY" | head -1)"
if [ -z "$SRC" ]; then
  echo "error: llama-server binary not found in archive" >&2
  exit 1
fi

# copy the whole archive directory (binary + shared libraries)
ARCHIVE_DIR="$(dirname "$SRC")"
rm -rf "$RES_DIR"
mkdir -p "$RES_DIR"
cp -R "$ARCHIVE_DIR"/. "$RES_DIR"/
chmod +x "$RES_DIR/$BINARY" 2>/dev/null || true

echo "version check"
VERSION_OUT="$("$RES_DIR/$BINARY" --version 2>&1 || true)"
BUILD_NUM="$(echo "$VERSION_OUT" | grep -oE 'build [0-9]+' | head -1 | grep -oE '[0-9]+')"
if [ -z "$BUILD_NUM" ] || [ "$BUILD_NUM" -lt "$MIN_BUILD" ]; then
  echo "error: llama-server build '$BUILD_NUM' below required $MIN_BUILD" >&2
  echo "$VERSION_OUT" >&2
  exit 1
fi
echo "ok: $RES_DIR (build $BUILD_NUM)"
echo "$VERSION_OUT"
