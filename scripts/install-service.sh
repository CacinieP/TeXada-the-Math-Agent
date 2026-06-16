#!/usr/bin/env bash
# Install TeXada backend services as macOS LaunchAgents.
# Run this once after the project is set up; services will start on login.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"
# Logs live under ~/.texada, NOT the project dir. If the project is cloned
# into a TCC-protected location (~/Desktop, ~/Documents, ~/Downloads), the
# background LaunchAgent cannot write logs there and exits with code 78
# (EX_CONFIG). ~/.texada is outside TCC scope and always writable.
LOG_DIR="$HOME/.texada/logs"
mkdir -p "$LOG_DIR"

if [ ! -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "❌ 未找到 $PROJECT_ROOT/.venv/bin/python"
    echo "   请先完成安装：pip install -e ."
    exit 1
fi

install_plist() {
    local name="$1"
    local src="$PROJECT_ROOT/scripts/launchd/$name.plist"
    local dest="$LAUNCH_AGENTS_DIR/$name.plist"

    if [ ! -f "$src" ]; then
        echo "❌ 缺少模板文件：$src"
        exit 1
    fi

    sed -e "s|{{PROJECT_ROOT}}|$PROJECT_ROOT|g" -e "s|{{LOG_DIR}}|$LOG_DIR|g" "$src" > "$dest"
    chmod 644 "$dest"
    echo "✅ 已生成 $dest"

    # Use the modern bootstrap/bootout API. The legacy `launchctl load`/`unload`
    # misbehave on recent macOS for agents that were previously unloaded:
    # the service loads but the process never actually starts (stuck at the
    # last exit code). `bootout` then `bootstrap` into the user GUI domain is
    # reliable. Label equals the plist filename (e.g. com.texada.api).
    local domain="gui/$(id -u)"
    launchctl bootout "$domain/$name" 2>/dev/null || true
    launchctl bootstrap "$domain" "$dest"
    echo "✅ 已加载 $name"
}

echo "🔧 安装 TeXada 后台服务..."
echo "   项目路径：$PROJECT_ROOT"

install_plist "com.texada.api"
install_plist "com.texada.web"

echo ""
echo "✨ 服务已安装并启动"
echo "   • API:    http://127.0.0.1:18732"
echo "   • Web UI: http://127.0.0.1:5173/"
echo ""
echo "查看状态："
echo "   launchctl list | grep com.texada"
echo ""
echo "查看日志："
echo "   tail -f $LOG_DIR/api-service.log"
echo "   tail -f $LOG_DIR/web-service.log"
