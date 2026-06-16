#!/usr/bin/env bash
# Uninstall TeXada backend LaunchAgents.
set -euo pipefail

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

uninstall_plist() {
    local name="$1"
    local dest="$LAUNCH_AGENTS_DIR/$name.plist"

    # bootout is the modern, reliable counterpart to the legacy `unload`.
    launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
    # Fall back to unload in case the service was loaded via the legacy API.
    launchctl unload "$dest" 2>/dev/null || true
    echo "✅ 已停止 $name"

    if [ -f "$dest" ]; then
        rm "$dest"
        echo "✅ 已删除 $dest"
    fi
}

echo "🧹 卸载 TeXada 后台服务..."
uninstall_plist "com.texada.api"
uninstall_plist "com.texada.web"
echo "✨ 服务已卸载"
