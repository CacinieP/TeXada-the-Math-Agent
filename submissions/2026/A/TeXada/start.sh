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

# ── Check Ollama ──
echo "🔍 Checking Ollama..."
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "⚠️  Ollama is not running. Please start it first:"
    echo "   ollama serve"
    exit 1
fi

MODELS=$(curl -s http://localhost:11434/api/tags | grep -o 'gemma4' || true)
if [[ -z "$MODELS" ]]; then
    echo "⬇️  Pulling Gemma 4 E4B..."
    ollama pull gemma4:e4b-it-qat
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
