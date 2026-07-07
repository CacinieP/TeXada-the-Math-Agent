# TeXada — Math Formula Agent

> 端侧数学公式 Agent，基于 **MiniCPM** 系模型，通过 **Ollama** 本地推理，零云端依赖。

TeXada 把自然语言、LaTeX 片段、手写公式图片统一转换成 LaTeX，并即时渲染（KaTeX / LaTeX 高亮）、校验、自动修复。双模型各司其职：

| 角色 | 模型 | 用途 |
|------|------|------|
| 文本推理 | **MiniCPM5-1B** (`hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M`) | 自然语言 → LaTeX、LaTeX 补全 |
| 视觉 OCR | **MiniCPM-V 4.6** (`openbmb/minicpm-v4.6:latest`) | 手写 / 截图公式识别 |

两个模型都跑在同一个本地 **Ollama** daemon 上（Ollama 提供 OpenAI 兼容的 `/v1` 端点，推理层直接复用标准 OpenAI Chat API）。

## 截图

![TeXada 运行截图](assets/clipboard-screenshot.png)

## 特性

- 🧮 **自然语言 → LaTeX**：「二重积分 f(x,y) 在区域 D 上」→ `\iint_D f(x,y)\,dx\,dy`
- ✍️ **LaTeX 补全**：`\sum_{i=1}^{` → `\sum_{i=1}^{n} x_i`
- 📷 **OCR 图片识别**：MiniCPM-V 多模态识别手写 / 截图公式
- ⚡ **快捷公式**：输入 `euler` → `e^{i\pi}+1=0`（可自定义）
- ✅ **自动校验 + 修复**：LaTeX 语法检查，错误自动尝试修复
- 🔒 **完全离线**：本地 Ollama，无任何云端调用

## 快速启动（macOS 双击 App）

完成下方「快速开始」的安装后，项目根会生成 **`TeXada.app`**，可以像普通桌面应用一样双击启动：

1. 在 Finder 双击 `TeXada.app`（首次运行可能需 **右键 → 打开** 以绕过 Gatekeeper）。
2. 通知栏提示启动进度，浏览器自动打开 http://127.0.0.1:5173/。
3. 服务在后台运行；关闭浏览器不会停止服务，需手动结束 `texada serve` 与 `http.server` 进程。

> 脚本会自动检测并尝试启动 Ollama（若未运行）。

如果更喜欢看到终端日志，也可以使用项目根下的 **`TeXada.command`**：

1. 在 Finder 双击 `TeXada.command`（首次运行可能需 **右键 → 打开**）。
2. 终端窗口显示启动日志，浏览器自动打开 http://127.0.0.1:5173/。
3. 关闭终端窗口或按 `Ctrl+C` 即停止全部服务。

## 快速开始

### 1. 安装 Ollama 并拉取 MiniCPM 模型

```bash
# 安装 Ollama: https://ollama.com
ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M   # 文本
ollama pull openbmb/minicpm-v4.6:latest             # 视觉 OCR
```

### 2. 安装 TeXada

```bash
git clone <repo>
cd TeXada-the-Math-Agent
pip install -e ".[dev]"
```

### 3. 检查就绪

```bash
texada check
```

预期输出：

```
TeXada v0.3.0 — System Check
  Ollama host:  http://localhost:11434
  Backend:      ollama
  Model:        hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M
  Vision model: openbmb/minicpm-v4.6:latest
  Ollama:       ✅ running
  Render mode:  katex
  Delimiter:    $$
```

### 4. 启动

```bash
texada serve          # 启动 FastAPI 后端，默认监听 TEXADA_API_HOST/TEXADA_API_PORT
# 或一键启动（含 macOS Swift 浮窗）：
./start.sh
```

桌面端启动：
- 双击 `TeXada.app`：无终端窗口，自动打开浏览器
- 双击 `TeXada Desktop.app`：原生菜单栏浮窗（需先 `./scripts/build-desktop-app.sh` 构建）

### 后台服务（开机自启）

如果希望 API 和前端在登录后自动后台运行、崩溃后自动重启，可安装 macOS LaunchAgent：

```bash
./scripts/install-service.sh
```

安装后：
- 服务会立即启动，并在每次登录时自动启动
- API: `http://${TEXADA_API_HOST:-127.0.0.1}:${TEXADA_API_PORT:-18732}`
- Web UI: `http://${TEXADA_WEB_HOST:-127.0.0.1}:${TEXADA_WEB_PORT:-5173}/`
- 日志：`~/.texada/logs/api-service.log`、`~/.texada/logs/web-service.log`

> ⚠️ **不要把项目克隆到 `~/Desktop`、`~/Documents`、`~/Downloads`**。
> 这三个是 macOS 的 **TCC 隐私保护位置**，后台 LaunchAgent 默认无权写入其中的文件 —— 服务会因无法写日志而以退出码 78（`EX_CONFIG`）反复崩溃、永远起不来。
> 推荐克隆到 `~/Projects/`、`~/Code/` 或家目录下任意非保护位置；日志已固定写到 `~/.texada/logs/`（非保护位置），不受项目目录影响。

卸载服务：

```bash
./scripts/uninstall-service.sh
```

### 原生桌面浮窗（macOS）

项目内置了一个基于 Swift + WKWebView 的菜单栏浮窗应用 **`TeXada Desktop.app`**：

- 常驻菜单栏，点击 𝑇 图标或使用全局快捷键 **⌥⌘T** 唤出
- 内置 Web UI，无需打开浏览器
- 支持拖拽浮窗、读写剪贴板、隐藏/显示窗口

**构建**（需要 Xcode Command Line Tools）：

```bash
./scripts/build-desktop-app.sh
```

构建完成后项目根会出现 `TeXada Desktop.app`。

**使用**：

1. 先启动后端（或安装后台服务 `./scripts/install-service.sh`）
2. 双击 `TeXada Desktop.app`（首次运行需 **右键 → 打开**）
3. 点击菜单栏 𝑇 图标即可使用

### 原生桌面浮窗（Windows）

Windows 版走 Tauri shell，界面复用 `tauri-shell/src/` 的静态前端，后端地址由运行时配置解析（`TEXADA_API_BASE` 优先，其次是 `TEXADA_API_HOST` / `TEXADA_API_PORT`）。

- 常驻系统托盘，点击托盘图标或使用全局快捷键 **Ctrl+Alt+T** 唤出
- 支持读写剪贴板、隐藏/显示窗口、文本补全与图片 OCR 桥接
- 支持云侧 OpenAI-compatible 后端配置，endpoint/model/key 由用户在界面中填写

**构建**（需要 Windows 主机、Rust、Microsoft C++ Build Tools、WebView2 Runtime、tauri-cli）：

```powershell
cargo install tauri-cli --version "^2" --locked
.\scripts\build-windows-app.ps1
```

构建完成后安装包位于 `tauri-shell\src-tauri\target\release\bundle\nsis\`。macOS 主机不直接产出 Windows 安装包；如需自动化产物，建议在 Windows CI runner 上执行该脚本。

### GitHub Actions 构建

仓库内置两个 workflow：

- `Audit`：push / PR / 手动触发，运行 Ruff、pytest、pip-audit、npm audit、JS 语法检查，以及 macOS/Windows Tauri `cargo check`
- `Desktop Release`：推送 `v*` tag 或手动触发；先跑预发布审计，通过后构建 macOS arm64 `.dmg`、macOS Intel `.dmg` 和 Windows x64 NSIS `.exe`，并上传到 draft release 与 workflow artifacts

macOS release 产物使用 ad-hoc signing；正式分发前仍建议接入 Developer ID 签名与 notarization。

## 配置

配置从 `~/.texada/config.json` 读取（也可用 `TEXADA_` 前缀环境变量覆盖）：

```json
{
  "backend": "ollama",
  "ollama_host": "http://localhost:11434",
  "model_name": "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
  "vision_model_name": "openbmb/minicpm-v4.6:latest",
  "api_host": "127.0.0.1",
  "api_port": 18732,
  "max_tokens": 2048,
  "default_render_mode": "katex"
}
```

> `max_tokens` 建议 ≥ 2048 —— MiniCPM5 是推理模型，思维链需要空间。

如果要改用自定义 OpenAI-compatible 云端模型，在设置页选择
`OpenAI-compatible` 后填写 endpoint、模型名和 API key；也可以直接写入：

```json
{
  "backend": "openai_compatible",
  "openai_base_url": "https://your-provider.example/v1",
  "openai_model_name": "your-text-or-vision-model",
  "openai_vision_model_name": "",
  "openai_api_key": "your-api-key"
}
```

`openai_vision_model_name` 留空时，OCR 会复用 `openai_model_name`。

## 架构

```
用户输入 (NL / LaTeX 片段 / 图片)
        │
   InputRouter ── 路由 ──┐
        │                │
   NL→LaTeX           OCR 图片
   MiniCPM5-1B        MiniCPM-V 4.6 (多模态)
   (Ollama /v1)       (Ollama /v1)
        │                │
        └── 校验 + 自动修复 + 渲染 (KaTeX) ──→ 输出
```

详见 [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md)。

## License

见 [LICENSE](LICENSE)。
