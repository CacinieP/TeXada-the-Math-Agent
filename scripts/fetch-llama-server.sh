#!/usr/bin/env bash
# Fetch the pinned llama-server binary for desktop packaging.
#
# Places llama-server-<target-triple> (plus .exe on Windows) into
# tauri-shell/src-tauri/binaries/ so Tauri externalBin can bundle it.
# SHA256 is pinned per asset; the extracted binary is version-checked
# (build >= 9049, required for MiniCPM-V 4.6).
#
# Usage: scripts/fetch-llama-server.sh [target-triple]
#   (default: rustc host triple)
set -euo pipefail

BUILD="b11046"
MIN_BUILD=9049

# asset per rust target triple
declare -A ASSETS=(
  ["aarch64-apple-darwin"]="llama-${BUILD}-bin-macos-arm64.tar.gz|96623092033e83545cd92316ff63d0378a976a4979735f80a1934cc128efb0ad"
  ["x86_64-apple-darwin"]="llama-${BUILD}-bin-macos-x64.tar.gz|df796167a64469d8ab805a71aadc9a531982f0b0d86a9b449df5fe72af26a065"
  ["x86_64-pc-windows-msvc"]="llama-${BUILD}-bin-win-cpu-x64.zip|dece5ebc80fbc48063540aa4c48fdc91c59328b7ea44c2bdf6e85ec4383b5fc7"
)
BASE_URL="https://github.com/ggml-org/llama.cpp/releases/download/${BUILD}"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  TARGET="$(rustc -vV | awk '/^host:/ {print $2}')"
fi

ENTRY="${ASSETS[$TARGET]:-}"
if [ -z "$ENTRY" ]; then
  echo "error: no pinned llama-server asset for target '$TARGET'" >&2
  echo "known targets: ${!ASSETS[*]}" >&2
  exit 1
fi
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
ACTUAL="$(shasum -a 256 "$WORK/$ASSET" | awk '{print $1}')"
if [ "$ACTUAL" != "$SHA" ]; then
  echo "error: sha256 mismatch for $ASSET" >&2
  echo "  expected: $SHA" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 1
fi

echo "extracting"
case "$ASSET" in
  *.tar.gz) tar -xzf "$WORK/$ASSET" -C "$WORK" ;;
  *.zip)    unzip -q "$WORK/$ASSET" -d "$WORK" ;;
esac

SRC="$(find "$WORK" -type f -name 'llama-server' | head -1)"
if [ -z "$SRC" ]; then
  echo "error: llama-server binary not found in archive" >&2
  exit 1
fi

# copy the whole archive directory (binary + shared libraries)
ARCHIVE_DIR="$(find "$WORK" -type d -name 'llama-*' | head -1)"
if [ -z "$ARCHIVE_DIR" ]; then
  echo "error: archive directory not found" >&2
  exit 1
fi
rm -rf "$RES_DIR"
mkdir -p "$RES_DIR"
cp -R "$ARCHIVE_DIR"/. "$RES_DIR"/
chmod +x "$RES_DIR/llama-server" 2>/dev/null || true

echo "version check"
VERSION_OUT="$("$RES_DIR/llama-server" --version 2>&1 || true)"
BUILD_NUM="$(echo "$VERSION_OUT" | grep -oE 'build [0-9]+' | head -1 | grep -oE '[0-9]+')"
if [ -z "$BUILD_NUM" ] || [ "$BUILD_NUM" -lt "$MIN_BUILD" ]; then
  echo "error: llama-server build '$BUILD_NUM' below required $MIN_BUILD" >&2
  echo "$VERSION_OUT" >&2
  exit 1
fi
echo "ok: $RES_DIR (build $BUILD_NUM)"
echo "$VERSION_OUT"
