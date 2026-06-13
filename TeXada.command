#!/usr/bin/env bash
# TeXada — 双击启动(macOS)
# 双击此文件即在终端启动 API + 前端，并自动打开浏览器。
# 前置：已完成 README 的「快速开始」安装（Ollama + 模型 + pip install -e .）。
set -uo pipefail

cd "$(dirname "$0")"

API_PORT=18732
WEB_PORT=5173
API_PID=""
WEB_PID=""

cleanup() {
    echo ""
    echo "🧹 关闭 TeXada..."
    [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
    [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# ── 检查 Ollama ──
echo "🔍 检查 Ollama..."
if ! curl -sf http://localhost:11434/v1/models >/dev/null 2>&1; then
    echo "  ⚠️  Ollama 未运行，尝试启动..."
    if command -v ollama >/dev/null 2>&1; then
        ollama serve >/dev/null 2>&1 &
        for _ in $(seq 1 10); do
            curl -sf http://localhost:11434/v1/models >/dev/null 2>&1 && break
            sleep 0.5
        done
    fi
fi
if curl -sf http://localhost:11434/v1/models >/dev/null 2>&1; then
    echo "  ✅ Ollama 就绪"
else
    echo "  ❌ Ollama 未运行。请先安装并启动：https://ollama.com"
    echo "     拉取模型：ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"
    echo "               ollama pull openbmb/minicpm-v4.6:latest"
    read -n 1 -s -r -p "按任意键关闭..."
    exit 1
fi

# ── 检查 Python 环境 ──
if [ ! -x ".venv/bin/python" ]; then
    echo "❌ 未找到 .venv/bin/python。请先运行："
    echo "   python3 -m venv .venv && .venv/bin/pip install -e ."
    read -n 1 -s -r -p "按任意键关闭..."
    exit 1
fi

# ── 启动 API ──
echo "🚀 启动 API（端口 $API_PORT）..."
.venv/bin/python -m texada serve >/dev/null 2>&1 &
API_PID=$!

# ── 启动前端（纯静态）──
echo "🌐 启动前端（端口 $WEB_PORT）..."
python3 -m http.server "$WEB_PORT" --bind 127.0.0.1 --directory tauri-shell/src >/dev/null 2>&1 &
WEB_PID=$!

# ── 等待 API 就绪 ──
echo "⏳ 等待 API 就绪..."
READY=false
for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$API_PORT/api/status" >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 0.5
done

if [ "$READY" != true ]; then
    echo "  ❌ API 启动超时。请检查上方日志。"
    cleanup
fi
echo "  ✅ API 就绪"

# ── 打开浏览器 ──
sleep 1
open "http://127.0.0.1:$WEB_PORT/"

echo ""
echo "✨ TeXada 已启动！"
echo "   • 前端：  http://127.0.0.1:$WEB_PORT/"
echo "   • API：   http://127.0.0.1:$API_PORT/"
echo "   • 关闭此窗口或按 Ctrl+C 停止所有服务。"
echo ""
wait "$API_PID"
