#!/usr/bin/env bash
# Build the pinned runtime on the same glibc baseline as the desktop/sidecar.
# Upstream Ubuntu binaries can require a newer glibc than our supported hosts.
set -euo pipefail
SOURCE_COMMIT=620d2225cc436ab0b001e3200e590e3b286ef9ab
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RES_DIR="$ROOT/tauri-shell/src-tauri/resources/llama-server"
WORK="$(mktemp -d)"
STAGED=""
trap 'rm -rf "$WORK"; if [ -n "$STAGED" ]; then rm -rf "$STAGED"; fi' EXIT
# Keep history: upstream derives build 11669 from the commit count.
git clone --filter=blob:none --no-checkout https://github.com/ggml-org/llama.cpp.git "$WORK/source"
git -C "$WORK/source" checkout --detach "$SOURCE_COMMIT"
test "$(git -C "$WORK/source" rev-parse HEAD)" = "$SOURCE_COMMIT"
cmake -S "$WORK/source" -B "$WORK/build" \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=OFF \
  -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build "$WORK/build" --target llama-server --parallel 2
VERSION_OUT="$("$WORK/build/bin/llama-server" --version 2>&1)"
grep -Eq '\bbuild[[:space:]]+11669\b' <<< "$VERSION_OUT"
mkdir -p "$(dirname "$RES_DIR")"
STAGED="$(mktemp -d "${RES_DIR}.staging.XXXXXX")"
cp -a "$WORK/build/bin"/. "$STAGED"/
python3 - "$STAGED/runtime-source.json" "$SOURCE_COMMIT" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": 1, "target": "x86_64-unknown-linux-gnu", "build": 11669,
    "source_commit": sys.argv[2], "build_mode": "native-source",
    "source_url": "https://github.com/ggml-org/llama.cpp/tree/" + sys.argv[2],
}, indent=2) + "\n")
PY
PREVIOUS="${RES_DIR}.previous.$$"
if [ -e "$RES_DIR" ]; then mv "$RES_DIR" "$PREVIOUS"; fi
if ! mv "$STAGED" "$RES_DIR"; then
  if [ -e "$PREVIOUS" ]; then mv "$PREVIOUS" "$RES_DIR"; fi
  exit 1
fi
STAGED=""
rm -rf "$PREVIOUS"
echo "$VERSION_OUT"
