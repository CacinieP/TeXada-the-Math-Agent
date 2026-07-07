#!/usr/bin/env bash
# TeXada — macOS double-click launcher.
set -euo pipefail

cd "$(dirname "$0")"

eval "$(python3 - <<'PY'
import json
import shlex
from pathlib import Path

cfg_path = Path.home() / ".texada" / "config.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        cfg = {}

values = {
    "TEXADA_CONFIG_BACKEND": cfg.get("backend", "ollama"),
    "TEXADA_CONFIG_OLLAMA_HOST": cfg.get("ollama_host", "http://localhost:11434"),
    "TEXADA_CONFIG_API_HOST": cfg.get("api_host", "127.0.0.1"),
    "TEXADA_CONFIG_API_PORT": str(cfg.get("api_port", 18732)),
    "TEXADA_CONFIG_WEB_HOST": cfg.get("web_host", "127.0.0.1"),
    "TEXADA_CONFIG_WEB_PORT": str(cfg.get("web_port", 5173)),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

BACKEND="${TEXADA_BACKEND:-${TEXADA_CONFIG_BACKEND:-ollama}}"
OLLAMA_HOST="${TEXADA_OLLAMA_HOST:-${TEXADA_CONFIG_OLLAMA_HOST:-http://localhost:11434}}"
API_HOST="${TEXADA_API_HOST:-${TEXADA_CONFIG_API_HOST:-127.0.0.1}}"
API_PORT="${TEXADA_API_PORT:-${TEXADA_CONFIG_API_PORT:-18732}}"
WEB_HOST="${TEXADA_WEB_HOST:-${TEXADA_CONFIG_WEB_HOST:-127.0.0.1}}"
WEB_PORT="${TEXADA_WEB_PORT:-${TEXADA_CONFIG_WEB_PORT:-5173}}"

export TEXADA_BACKEND="$BACKEND"
export TEXADA_OLLAMA_HOST="$OLLAMA_HOST"
export TEXADA_API_HOST="$API_HOST"
export TEXADA_API_PORT="$API_PORT"

API_PID=""
WEB_PID=""

cleanup() {
    echo ""
    echo "关闭 TeXada..."
    [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
    [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

if [ "$BACKEND" = "ollama" ]; then
    OLLAMA_BASE="${OLLAMA_HOST%/}"
    OLLAMA_BASE="${OLLAMA_BASE%/v1}"
    OLLAMA_MODELS_URL="$OLLAMA_BASE/v1/models"
    echo "检查 Ollama: $OLLAMA_BASE"
    if ! curl -sf "$OLLAMA_MODELS_URL" >/dev/null 2>&1; then
        echo "  Ollama 未响应，尝试启动..."
        if command -v ollama >/dev/null 2>&1; then
            ollama serve >/dev/null 2>&1 &
            for _ in $(seq 1 20); do
                curl -sf "$OLLAMA_MODELS_URL" >/dev/null 2>&1 && break
                sleep 0.5
            done
        fi
    fi
    if curl -sf "$OLLAMA_MODELS_URL" >/dev/null 2>&1; then
        echo "  Ollama 就绪"
    else
        echo "  Ollama 未运行。可设置 TEXADA_OLLAMA_HOST 或 ~/.texada/config.json 的 ollama_host。"
        read -r -n 1 -s -p "按任意键关闭..."
        exit 1
    fi
else
    echo "使用 $BACKEND 后端，跳过本地 Ollama 检查。"
fi

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

if ! python -c "import texada" >/dev/null 2>&1; then
    echo "安装 TeXada..."
    python -m pip install -q -e .
fi

echo "启动 API: http://$API_HOST:$API_PORT"
python -m texada serve --host "$API_HOST" --port "$API_PORT" >/dev/null 2>&1 &
API_PID=$!

echo "启动前端: http://$WEB_HOST:$WEB_PORT/"
python3 -m http.server "$WEB_PORT" --bind "$WEB_HOST" --directory tauri-shell/src >/dev/null 2>&1 &
WEB_PID=$!

READY=false
for _ in $(seq 1 40); do
    if curl -sf "http://$API_HOST:$API_PORT/api/status" >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 0.5
done

if [ "$READY" != true ]; then
    echo "API 启动超时。"
    cleanup
fi

sleep 0.5
open "http://$WEB_HOST:$WEB_PORT/" >/dev/null 2>&1 || true

echo ""
echo "TeXada 已启动。"
echo "  前端: http://$WEB_HOST:$WEB_PORT/"
echo "  API:  http://$API_HOST:$API_PORT/"
echo "关闭此窗口或按 Ctrl+C 停止。"
wait "$API_PID"
