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

# ── Check Ollama daemon ──
echo "🔍 Checking Ollama daemon..."

OLLAMA_OK=false
if curl -s http://localhost:11434/v1/models >/dev/null 2>&1; then
    echo "  ✅ Ollama running on :11434 (MiniCPM5-1B + MiniCPM-V 4.6)"
    OLLAMA_OK=true
else
    echo "  ⚠️  Ollama not running on :11434 — attempting 'ollama serve'..."
    ollama serve >/dev/null 2>&1 &
    for _ in {1..10}; do
        sleep 0.5
        if curl -s http://localhost:11434/v1/models >/dev/null 2>&1; then
            echo "  ✅ Ollama started"
            OLLAMA_OK=true
            break
        fi
    done
fi

if [[ "$OLLAMA_OK" != "true" ]]; then
    echo ""
    echo "❌ Ollama is required. Please install & start it:"
    echo "   https://ollama.com  →  ollama serve"
    echo "   Then pull the MiniCPM models:"
    echo "   ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"
    echo "   ollama pull openbmb/minicpm-v4.6:latest"
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

# ── Start native desktop shell (macOS only) ──
DESKTOP_APP=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ -d "TeXada Desktop.app" ]]; then
        DESKTOP_APP="TeXada Desktop.app"
    elif [[ -d "tauri-shell/TeXadaShell/TeXadaShell.app" ]]; then
        DESKTOP_APP="tauri-shell/TeXadaShell/TeXadaShell.app"
    fi
fi

if [[ -n "$DESKTOP_APP" ]]; then
    echo "🖥️  Starting native desktop shell..."
    open "$DESKTOP_APP"
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
    echo "   (Native desktop shell only available on macOS with compiled .app)"
    echo "   Build it with: ./scripts/build-desktop-app.sh"
    echo ""
    echo "Press Ctrl+C to stop."
    wait "$API_PID"
fi
