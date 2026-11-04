#!/usr/bin/env bash
# Fetch the pinned llama-server binary for desktop packaging.
#
# Places the native binary and its libraries in the Tauri resource directory.
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
  x86_64-unknown-linux-gnu) ENTRY="llama-${BUILD}-bin-ubuntu-x64.tar.gz|cf07c1c112d709bd67e522017471de57ed0ec8bea031d732c5422351c07f65ac" ;;
  *) echo "error: no pinned llama-server asset for target '$TARGET'" >&2; exit 1 ;;
esac
ASSET="${ENTRY%%|*}"
SHA="${ENTRY##*|}"

SHA_PYTHON="${TEXADA_BUILD_PYTHON:-}"
if [ -z "$SHA_PYTHON" ]; then
  for candidate in python3.12 python3.13 python3.14 python3 python; do
    found="$(command -v "$candidate" || true)"
    if [ -n "$found" ] && "$found" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
      SHA_PYTHON="$found"
      break
    fi
  done
fi
if [ -z "$SHA_PYTHON" ] || ! "$SHA_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
  echo "error: Python 3.12+ is required for safe runtime archive extraction; set TEXADA_BUILD_PYTHON." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# llama-server is dynamically linked (libggml/libllama dylibs on macOS, DLLs
# on Windows), so the whole build/bin directory ships together as a Tauri
# resource, next to the texada-backend sidecar.
RES_DIR="$ROOT/tauri-shell/src-tauri/resources/llama-server"
mkdir -p "$(dirname "$RES_DIR")"

WORK="$(mktemp -d)"
STAGED=""
trap 'rm -rf "$WORK"; if [ -n "$STAGED" ]; then rm -rf "$STAGED"; fi' EXIT

echo "downloading $ASSET (build $BUILD) for $TARGET"
curl -fsSL --retry 3 --connect-timeout 20 --max-time 600 -o "$WORK/$ASSET" "$BASE_URL/$ASSET"

echo "verifying sha256"
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
mkdir "$WORK/extracted"
"$SHA_PYTHON" - "$WORK/$ASSET" "$WORK/extracted" <<'PYEXTRACT'
import sys
import tarfile
import zipfile
from pathlib import PurePosixPath

path, destination = sys.argv[1:]
if path.endswith(".tar.gz"):
    with tarfile.open(path) as archive:
        archive.extractall(destination, filter="data")
else:
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or ":" in name.parts[0]:
                raise ValueError("Unsafe runtime archive path")
        archive.extractall(destination)
PYEXTRACT

BINARY="llama-server"
case "$TARGET" in *windows*) BINARY="llama-server.exe" ;; esac
SRC="$("$SHA_PYTHON" - "$WORK/extracted" "$BINARY" <<'PYSOURCE'
from pathlib import Path
import sys
matches = [path for path in Path(sys.argv[1]).rglob(sys.argv[2]) if path.is_file()]
if len(matches) != 1:
    raise SystemExit("Runtime archive must contain exactly one llama-server binary")
print(matches[0])
PYSOURCE
)"

echo "version check"
chmod +x "$SRC"
if ! VERSION_OUT="$("$SRC" --version 2>&1)"; then
  echo "error: pinned llama-server could not execute its version check" >&2
  echo "$VERSION_OUT" >&2
  exit 1
fi
BUILD_NUM="$(printf '%s' "$VERSION_OUT" | "$SHA_PYTHON" -c 'import re, sys; match = re.search(r"\bbuild\s+(\d+)\b", sys.stdin.read()); print(match[1] if match else "")')"
if [ -z "$BUILD_NUM" ] || [ "$BUILD_NUM" -ne "$MIN_BUILD" ]; then
  echo "error: llama-server build '$BUILD_NUM' does not match pinned $MIN_BUILD" >&2
  echo "$VERSION_OUT" >&2
  exit 1
fi

# Validate before replacing an existing resource tree; a failed download or
# non-executable runtime must not leave a package containing a partial update.
ARCHIVE_DIR="$(dirname "$SRC")"
STAGED="$(mktemp -d "${RES_DIR}.staging.XXXXXX")"
cp -R "$ARCHIVE_DIR"/. "$STAGED"/
"$SHA_PYTHON" - "$STAGED/runtime-source.json" "$TARGET" "$BUILD_NUM" "$ASSET" "$SHA" "$BASE_URL/$ASSET" <<'PYRECEIPT'
import json
from pathlib import Path
import sys
path, target, build, archive, sha256, url = sys.argv[1:]
Path(path).write_text(json.dumps({"schema_version": 1, "target": target, "build": int(build),
    "archive": archive, "archive_sha256": sha256, "source_url": url}, indent=2) + "\n")
PYRECEIPT
PREVIOUS="${RES_DIR}.previous.$$"
if [ -e "$RES_DIR" ]; then mv "$RES_DIR" "$PREVIOUS"; fi
if ! mv "$STAGED" "$RES_DIR"; then
  if [ -e "$PREVIOUS" ]; then mv "$PREVIOUS" "$RES_DIR"; fi
  exit 1
fi
STAGED=""
rm -rf "$PREVIOUS"
echo "ok: $RES_DIR (build $BUILD_NUM)"
echo "$VERSION_OUT"
