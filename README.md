# TeXada — Math Formula Agent

> 中文：端侧优先的数学公式 Agent。默认使用 Ollama + MiniCPM 本地推理，也支持任意 OpenAI API 兼容的云侧模型。
> English: A local-first math formula agent. It defaults to Ollama + MiniCPM local inference and also supports any OpenAI API-compatible cloud model.

![TeXada screenshot](assets/clipboard-screenshot.png)

## 功能 / Features

| 中文 | English |
|------|---------|
| 自然语言转 LaTeX | Natural language to LaTeX |
| LaTeX 片段补全 | LaTeX fragment completion |
| 图片/截图公式 OCR | Formula OCR from images or screenshots |
| 快捷公式缩写 | User-editable formula snippets |
| LaTeX 校验、自动修复、KaTeX 渲染 | LaTeX validation, repair and KaTeX rendering |
| 点击公式块可在系统光标处键入公式；复制按钮仍只复制 | Click a formula block to type it at the system cursor; copy buttons still only copy |
| 设置页切换中文/英文和 80%-140% UI 缩放 | Settings switch Chinese/English and 80%-140% UI zoom |
| Tauri 浮窗支持托盘、全局快捷键、拖动标题栏 | Tauri popup supports tray, global shortcut and draggable title bar |

## 模型 / Models

| 角色 / Role | 默认模型 / Default model | 用途 / Purpose |
|-------------|--------------------------|----------------|
| 本地文本 / Local text | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | NL->LaTeX and completion |
| 本地视觉 / Local vision | `openbmb/minicpm-v4.6:latest` | OCR for handwritten or screenshot formulas |
| 云侧文本/视觉 / Cloud text/vision | Any OpenAI-compatible model | User-configured endpoint, model, vision model and API key |

中文：本地 Ollama 默认地址是 `http://localhost:11434`，但这不是硬编码要求。可以在设置页、`~/.texada/config.json` 或 `TEXADA_OLLAMA_HOST` 改成任意端口/主机；`localhost:11435` 和 `http://localhost:11435/v1` 都会被自动规范化。
English: The local Ollama default is `http://localhost:11434`, but it is not fixed. Change it in Settings, `~/.texada/config.json`, or `TEXADA_OLLAMA_HOST`; both `localhost:11435` and `http://localhost:11435/v1` are normalized automatically.

## 快速开始 / Quick Start

### 1. 安装模型 / Install models

```bash
ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M
ollama pull openbmb/minicpm-v4.6:latest
```

### 2. 安装应用 / Install the app

```bash
git clone https://github.com/CacinieP/TeXada-the-Math-Agent.git
cd TeXada-the-Math-Agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

### 3. 检查 / Check

```bash
texada check
```

### 4. 启动 / Run

```bash
./start.sh
```

中文：`start.sh` 会读取 `TEXADA_OLLAMA_HOST`、`TEXADA_API_HOST`、`TEXADA_API_PORT`、`TEXADA_WEB_HOST`、`TEXADA_WEB_PORT` 和 `~/.texada/config.json`。
English: `start.sh` reads `TEXADA_OLLAMA_HOST`, `TEXADA_API_HOST`, `TEXADA_API_PORT`, `TEXADA_WEB_HOST`, `TEXADA_WEB_PORT`, and `~/.texada/config.json`.

macOS 也可双击 `TeXada.command`。
On macOS, you can also double-click `TeXada.command`.

## 桌面端 / Desktop

| 平台 / Platform | 构建 / Build |
|-----------------|--------------|
| macOS | GitHub Actions builds signed arm64 and Intel `.dmg` packages |
| Windows | GitHub Actions builds x64 NSIS `.exe`; locally use `scripts/build-windows-app.ps1` |

```powershell
cargo install tauri-cli --version "^2" --locked
.\scripts\build-windows-app.ps1
```

中文：Tauri 桌面端会从 `TEXADA_API_BASE` 读取完整 API 地址；没有该变量时使用 `TEXADA_API_HOST`/`TEXADA_API_PORT`，默认 `127.0.0.1:18732`。
English: The Tauri desktop shell reads `TEXADA_API_BASE` first. Without it, it uses `TEXADA_API_HOST`/`TEXADA_API_PORT`, defaulting to `127.0.0.1:18732`.

## 配置 / Configuration

配置文件 / Config file:

```json
{
  "backend": "ollama",
  "ollama_host": "http://localhost:11434",
  "model_name": "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
  "vision_model_name": "openbmb/minicpm-v4.6:latest",
  "api_host": "127.0.0.1",
  "api_port": 18732,
  "ui_language": "zh",
  "ui_zoom": 1.0,
  "max_tokens": 2048
}
```

云侧 OpenAI-compatible 示例 / Cloud OpenAI-compatible example:

```json
{
  "backend": "openai_compatible",
  "openai_base_url": "https://your-provider.example/v1",
  "openai_model_name": "your-text-model",
  "openai_vision_model_name": "your-vision-model",
  "openai_api_key": "your-api-key"
}
```

环境变量 / Environment variables:

| 变量 / Variable | 说明 / Description |
|-----------------|--------------------|
| `TEXADA_OLLAMA_HOST` | Local Ollama base URL, any host/port |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI bind address |
| `TEXADA_WEB_HOST`, `TEXADA_WEB_PORT` | Local browser launcher address |
| `TEXADA_API_BASE` | Explicit desktop shell API base |
| `TEXADA_API_TIMEOUT_SECS` | Tauri API request timeout |

## 交互 / Interaction

| 操作 / Action | 快捷键 / Shortcut |
|---------------|-------------------|
| 显示/隐藏浮窗 / Show or hide popup | macOS `Option+Command+T`, Windows `Ctrl+Alt+T` |
| 切换渲染模式 / Toggle render mode | macOS `Command+K`, Windows `Ctrl+K` |
| 放大 / Zoom in | `Command/Ctrl + +` |
| 缩小 / Zoom out | `Command/Ctrl + -` |
| 重置缩放 / Reset zoom | `Command/Ctrl + 0` |
| 拖动窗口 / Move window | Drag the title bar |

## 硬件与实测 / Hardware And Measurements

推荐 / Recommended:

| 场景 / Scenario | 建议 / Recommendation |
|-----------------|-----------------------|
| 文本转换和补全 / Text conversion and completion | Apple Silicon, Intel i5/Ryzen 5 or better, 8GB RAM |
| 常用 OCR / Frequent OCR | Apple Silicon M2/M3 class or better, 16GB RAM |
| 高频 OCR / Heavy OCR | 16GB+ RAM, discrete GPU or a cloud vision model |

2026-07-07 实测环境：macOS 26.5.1, arm64, Apple A18 Pro, 8GB RAM, Ollama local models.
Measured on 2026-07-07: macOS 26.5.1, arm64, Apple A18 Pro, 8GB RAM, local Ollama models.

| 操作 / Operation | 模型 / Model | 响应 / Latency |
|------------------|--------------|----------------|
| NL->LaTeX cold | MiniCPM5-1B | 179204.3ms |
| NL->LaTeX warm | MiniCPM5-1B | 29612.2ms |
| LaTeX completion | MiniCPM5-1B / rules | 1808.5ms |
| OCR sample | MiniCPM-V 4.6 | 39419.0ms |

## GitHub Actions

| Workflow | 中文 | English |
|----------|------|---------|
| `Audit` | Ruff、pytest、pip-audit、npm audit、JS 语法检查、Tauri cargo check | Ruff, pytest, pip-audit, npm audit, JS syntax check and Tauri cargo check |
| `Desktop Release` | 先预审计，再构建 macOS arm64/Intel DMG 和 Windows x64 NSIS EXE | Runs pre-release audit, then builds macOS arm64/Intel DMG and Windows x64 NSIS EXE |

macOS release secrets:

| Secret | 中文 | English |
|--------|------|---------|
| `APPLE_CERTIFICATE` | base64 编码的 `.p12` 证书 | base64-encoded `.p12` certificate |
| `APPLE_CERTIFICATE_PASSWORD` | `.p12` 导出密码 | `.p12` export password |
| `APPLE_SIGNING_IDENTITY` | 签名身份，例如 `Yichun Deng` | Signing identity, e.g. `Yichun Deng` |
| `APPLE_TEAM_ID` | Apple Team ID | Apple Team ID |

中文：当前 workflow 会签名并验证 DMG。Notarization 是单独步骤，需要 Developer ID/notary 凭据。
English: The current workflow signs and verifies DMGs. Notarization is separate and requires Developer ID/notary credentials.

## 开发 / Development

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uvx pip-audit --strict
npm ci
npm audit --audit-level=moderate
node --check tauri-shell/src/main.js
cd tauri-shell/src-tauri && cargo check
```

## 文档 / Docs

- [Architecture](docs/architecture.md)
- [Source audit](docs/audit.md)
- [Technical report](TECHNICAL_REPORT.md)

## License

TeXada-the-Math-Agent is released under `GPL-3.0-or-later`. See [LICENSE](LICENSE).
