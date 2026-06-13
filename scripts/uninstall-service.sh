#!/usr/bin/env bash
# Uninstall TeXada backend LaunchAgents.
set -euo pipefail

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

uninstall_plist() {
    local name="$1"
    local dest="$LAUNCH_AGENTS_DIR/$name.plist"

    if launchctl list | grep -q "^$name\$"; then
        launchctl unload "$dest" 2>/dev/null || true
        echo "✅ 已停止 $name"
    fi

    if [ -f "$dest" ]; then
        rm "$dest"
        echo "✅ 已删除 $dest"
    fi
}

echo "🧹 卸载 TeXada 后台服务..."
uninstall_plist "com.texada.api"
uninstall_plist "com.texada.web"
echo "✨ 服务已卸载"
