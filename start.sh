#!/usr/bin/env bash
# TeXada — One-shot startup script
set -euo pipefail

cd "$(dirname "$0")"

API_PORT=18732
API_PID=""

cleanup() {
    echo "
🧹 Shutting down TeXada..."
    if [[ -n "$API_PID" ]]; then
        kill "$API_PID" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup INT TERM

# ── Check llama.cpp servers ──
echo "🔍 Checking llama.cpp servers..."

TEXT_OK=false
VISION_OK=false

if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "  ✅ Text model (MiniCPM5-1B) on :8080"
    TEXT_OK=true
else
    echo "  ❌ Text model not running on :8080"
fi

if curl -s http://localhost:8081/health >/dev/null 2>&1; then
    echo "  ✅ Vision model (MiniCPM-V 4.6) on :8081"
    VISION_OK=true
else
    echo "  ⚠️  Vision model not running on :8081 (OCR disabled)"
fi

if [[ "$TEXT_OK" != "true" ]]; then
    echo ""
    echo "❌ Text model server is required. Please start llama.cpp first:"
    echo "   ~/models/start-minicpm-dual-opencode.ps1"
    echo "   # or manually:"
    echo "   llama-server -m <model.gguf> --port 8080 -ngl 99 -c 4096"
    exit 1
fi

# ── Check Python env ──
if [[ -d ".venv" ]]; then
    source .venv/bin/activate
fi

echo "📦 Checking Python dependencies..."
pip install -q -r requirements.txt 2>/dev/null || true

# ── Start API server ──
echo "🚀 Starting FastAPI server on port $API_PORT..."
python -m texada serve &
API_PID=$!

# Wait for API to be ready
for i in {1..30}; do
    if curl -s http://127.0.0.1:$API_PORT/api/status >/dev/null 2>&1; then
        echo "✅ API ready"
        break
    fi
    sleep 0.5
done

# ── Start Swift shell (macOS only) ──
if [[ "$OSTYPE" == "darwin"* ]] && [[ -d "tauri-shell/TeXadaShell/TeXadaShell.app" ]]; then
    echo "🖥️  Starting Swift floating shell..."
    open tauri-shell/TeXadaShell/TeXadaShell.app
    echo ""
    echo "✨ TeXada is running!"
    echo "   • API:     http://127.0.0.1:$API_PORT"
    echo "   • Shell:   Click the 𝑇 icon in your menu bar or press ⌥⌘T"
    echo ""
    echo "Press Ctrl+C to stop."
    wait "$API_PID"
else
    echo ""
    echo "✨ API server is running at http://127.0.0.1:$API_PORT"
    echo "   (Swift shell only available on macOS with compiled .app)"
    echo ""
    echo "Press Ctrl+C to stop."
    wait "$API_PID"
fi
