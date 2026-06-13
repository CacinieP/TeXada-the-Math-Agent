#!/usr/bin/env bash
# Build the native macOS TeXada desktop app (Swift + WKWebView menu bar shell).
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="$PROJECT_ROOT/tauri-shell/TeXadaShell/TeXadaShell"
BUILD_DIR="$PROJECT_ROOT/build/desktop"
APP_NAME="TeXada Desktop"
BUNDLE_ID="com.texada.desktop"
VERSION="0.3.0"

echo "🔨 构建 TeXada 桌面应用..."
echo "   项目路径：$PROJECT_ROOT"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "❌ 未找到 Swift 源码目录：$SOURCE_DIR"
    exit 1
fi

if ! command -v swiftc >/dev/null 2>&1; then
    echo "❌ 未找到 swiftc。请安装 Xcode Command Line Tools："
    echo "   xcode-select --install"
    exit 1
fi

mkdir -p "$BUILD_DIR"

# ── Compile Swift sources ──
echo "⚙️  编译 Swift 源码..."
swiftc \
    -o "$BUILD_DIR/TeXadaDesktop" \
    -framework Cocoa \
    -framework WebKit \
    "$SOURCE_DIR/AppDelegate.swift" \
    "$SOURCE_DIR/WebViewController.swift" \
    "$SOURCE_DIR/main.swift"

echo "✅ 编译完成"

# ── Assemble .app bundle ──
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$BUILD_DIR/TeXadaDesktop" "$APP_BUNDLE/Contents/MacOS/TeXadaDesktop"
chmod +x "$APP_BUNDLE/Contents/MacOS/TeXadaDesktop"

# Copy web assets
ASSETS_SRC="$SOURCE_DIR/assets"
ASSETS_DEST="$APP_BUNDLE/Contents/Resources/assets"
if [ -d "$ASSETS_SRC" ]; then
    cp -R "$ASSETS_SRC" "$ASSETS_DEST"
else
    echo "⚠️  未找到 assets 目录：$ASSETS_SRC"
fi

# Copy icon if available
ICON_SRC="$PROJECT_ROOT/assets/TeXada.icns"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
fi

# Write Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>TeXadaDesktop</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>
    <string>TeXada</string>
    <key>CFBundleDisplayName</key>
    <string>TeXada</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
</dict>
</plist>
EOF

# Ad-hoc sign
codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null 2>&1 || true

echo "✅ 桌面应用已生成：$APP_BUNDLE"

# ── Copy to project root ──
ROOT_APP="$PROJECT_ROOT/$APP_NAME.app"
rm -rf "$ROOT_APP"
cp -R "$APP_BUNDLE" "$ROOT_APP"
echo "✅ 已复制到项目根：$ROOT_APP"

echo ""
echo "使用说明："
echo "   1. 确保后端服务在运行（./scripts/install-service.sh）"
echo "   2. 双击 '$APP_NAME.app'"
echo "   3. 点击菜单栏 𝑇 图标或使用 ⌥⌘T 唤出浮窗"
