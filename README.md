# TeXada

<p align="center">
  <a href="#english">English</a>
  ·
  <a href="#中文">中文</a>
</p>

<p align="center">
  <a href="https://github.com/CacinieP/TeXada-the-Math-Agent/releases"><img alt="Release" src="https://img.shields.io/github/v/release/CacinieP/TeXada-the-Math-Agent?label=release"></a>
  <a href="https://github.com/CacinieP/TeXada-the-Math-Agent/actions/workflows/audit.yml"><img alt="Audit" src="https://github.com/CacinieP/TeXada-the-Math-Agent/actions/workflows/audit.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
</p>

![TeXada desktop screenshot](assets/clipboard-screenshot.png)

<a id="english"></a>

<details open>
<summary><strong>English</strong></summary>

## TeXada

TeXada is a desktop math formula agent for converting natural language, partial LaTeX, and screenshots into usable formula blocks. It is local-first with Ollama + MiniCPM by default, and it can also use any OpenAI API-compatible cloud endpoint.

### Highlights

| Capability | Description |
|------------|-------------|
| Natural language to LaTeX | Describe a formula and get copyable LaTeX or Markdown |
| Formula OCR | Paste or drop screenshots and images for formula recognition |
| Completion | Complete partial LaTeX expressions |
| Validation and repair | Check, fix, render and highlight LaTeX |
| Snippets and history | Keep reusable formula shortcuts and recent conversions |
| Desktop insertion | Click a formula block to type it at the system cursor |
| UI controls | Switch language, zoom from 80% to 140%, and drag the floating window |
| Release packages | Signed macOS DMGs and Windows x64 NSIS installers from GitHub Actions |

The Ollama port is configurable. The default is `http://localhost:11434`, but Settings, `~/.texada/config.json`, and `TEXADA_OLLAMA_HOST` can point TeXada at any host or port.

### Download

Version `0.1.0` is released from the `main` branch.

| Platform | Package |
|----------|---------|
| macOS Apple Silicon | signed `.dmg` |
| macOS Intel | signed `.dmg` |
| Windows x64 | NSIS `.exe` installer |

Release page: [github.com/CacinieP/TeXada-the-Math-Agent/releases](https://github.com/CacinieP/TeXada-the-Math-Agent/releases)

### Model Setup

Local Ollama models:

```bash
ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M
ollama pull openbmb/minicpm-v4.6:latest
```

| Role | Default | Notes |
|------|---------|-------|
| Text | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | Natural language conversion and completion |
| Vision | `openbmb/minicpm-v4.6:latest` | OCR from screenshots and images |
| Cloud | any OpenAI-compatible model | User-defined endpoint, text model, vision model and API key |

The vision slot supports MiniCPM-V 4.6, MiniCPM 5 1B compatible vision endpoints, and OpenAI API-compatible cloud vision models.

OpenAI-compatible example:

```json
{
  "backend": "openai_compatible",
  "openai_base_url": "https://your-provider.example/v1",
  "openai_model_name": "your-text-model",
  "openai_vision_model_name": "your-vision-model",
  "openai_api_key": "your-api-key"
}
```

### Configuration

Persistent config lives at `~/.texada/config.json`.

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

| Variable | Purpose |
|----------|---------|
| `TEXADA_OLLAMA_HOST` | Local Ollama base URL, including custom ports |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI bind address |
| `TEXADA_WEB_HOST`, `TEXADA_WEB_PORT` | Local browser launcher address |
| `TEXADA_API_BASE` | Explicit desktop shell API base |
| `TEXADA_API_TIMEOUT_SECS` | Desktop API request timeout |

### Run From Source

```bash
git clone https://github.com/CacinieP/TeXada-the-Math-Agent.git
cd TeXada-the-Math-Agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
texada check
./start.sh
```

On macOS, `TeXada.command` launches the same local API and web UI.

### Desktop Build

GitHub Actions builds release installers from `main` and version tags.

| Workflow | Checks |
|----------|--------|
| `Audit` | Ruff, pytest, pip-audit, npm audit, JS syntax check, Tauri cargo check on macOS and Windows |
| `Desktop Release` | Pre-release audit, signed macOS arm64/Intel DMG, Windows x64 NSIS installer |

Local Windows helper:

```powershell
cargo install tauri-cli --version "^2" --locked
.\scripts\build-windows-app.ps1
```

macOS release signing expects:

| Secret | Purpose |
|--------|---------|
| `APPLE_CERTIFICATE` | base64-encoded `.p12` certificate |
| `APPLE_CERTIFICATE_PASSWORD` | `.p12` export password |
| `APPLE_SIGNING_IDENTITY` | signing identity, for example `Yichun Deng` |
| `APPLE_TEAM_ID` | Apple Team ID |

The workflow signs and verifies DMGs. Notarization is separate and requires Developer ID/notary credentials.

### Shortcuts

| Action | Shortcut |
|--------|----------|
| Show or hide popup | macOS `Option+Command+T`, Windows `Ctrl+Alt+T` |
| Toggle render mode | macOS `Command+K`, Windows `Ctrl+K` |
| Zoom in | `Command/Ctrl + +` |
| Zoom out | `Command/Ctrl + -` |
| Reset zoom | `Command/Ctrl + 0` |
| Move window | drag the title bar |

### Hardware And Measurements

The numbers below are real local measurements from 2026-07-07, not synthetic benchmark data. Latency depends on model size, quantization, machine load and whether the model is warm.

Measured environment: macOS 26.5.1, arm64, Apple A18 Pro, 8GB RAM, local Ollama models.

| Scenario | Recommended hardware |
|----------|----------------------|
| Text conversion and completion | Apple Silicon, Intel i5/Ryzen 5 or better, 8GB RAM |
| Regular screenshot OCR | Apple Silicon M2/M3 class or better, 16GB RAM |
| Heavy OCR or larger models | 16GB+ RAM, discrete GPU, or a cloud vision model |

| Operation | Model | Observed latency |
|-----------|-------|------------------|
| NL to LaTeX, cold | MiniCPM5-1B | 179204.3ms |
| NL to LaTeX, warm | MiniCPM5-1B | 29612.2ms |
| LaTeX completion | MiniCPM5-1B plus rules | 1808.5ms |
| OCR sample | MiniCPM-V 4.6 | 39419.0ms |

### Quality Gate

The current `main` branch has no known blocking issue after the latest audit pass. That means tests and static checks pass; it is not a mathematical promise that no software bug can exist.

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uvx pip-audit --strict
npm ci
npm audit --audit-level=moderate
node --check tauri-shell/src/main.js
cd tauri-shell/src-tauri && cargo check
```

### Documentation

- [Architecture](docs/architecture.md)
- [Source audit](docs/audit.md)
- [Technical report](TECHNICAL_REPORT.md)

### License

TeXada-the-Math-Agent is released under `GPL-3.0-or-later`. See [LICENSE](LICENSE).

</details>

<a id="中文"></a>

<details>
<summary><strong>中文</strong></summary>

## TeXada

TeXada 是一个面向数学写作、公式整理和截图识别的桌面公式 Agent。默认本地使用 Ollama + MiniCPM，也支持任何 OpenAI API 兼容的云侧模型。

### 亮点

| 能力 | 说明 |
|------|------|
| 自然语言转 LaTeX | 输入公式描述，生成可复制的 LaTeX 或 Markdown |
| 公式 OCR | 粘贴或拖入截图/图片来识别公式 |
| 公式补全 | 补全未写完的 LaTeX 表达式 |
| 校验与修复 | 检查、修复、渲染并高亮 LaTeX |
| 缩写与历史 | 保存常用公式缩写和最近转换记录 |
| 桌面键入 | 点击公式块即可在系统当前光标处键入公式 |
| 界面控制 | 设置页切换中英文、80% 到 140% 缩放、拖动浮窗 |
| 安装包发布 | GitHub Actions 构建签名 macOS DMG 和 Windows x64 NSIS 安装包 |

Ollama 端口不是写死的。默认地址是 `http://localhost:11434`，但可以在设置页、`~/.texada/config.json` 或 `TEXADA_OLLAMA_HOST` 中改为任意主机和端口。

### 下载

版本 `0.1.0` 从 `main` 分支发布。

| 平台 | 安装包 |
|------|--------|
| macOS Apple Silicon | 已签名 `.dmg` |
| macOS Intel | 已签名 `.dmg` |
| Windows x64 | NSIS `.exe` 安装器 |

Release 页面：[github.com/CacinieP/TeXada-the-Math-Agent/releases](https://github.com/CacinieP/TeXada-the-Math-Agent/releases)

### 模型配置

本地 Ollama 模型：

```bash
ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M
ollama pull openbmb/minicpm-v4.6:latest
```

| 角色 | 默认模型 | 说明 |
|------|----------|------|
| 文本 | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | 自然语言转换和补全 |
| 视觉 | `openbmb/minicpm-v4.6:latest` | 从截图和图片识别公式 |
| 云侧 | 任意 OpenAI API 兼容模型 | 自定义 endpoint、文本模型、视觉模型和 API key |

视觉模型位支持 MiniCPM-V 4.6、MiniCPM 5 1B 兼容视觉端点，以及 OpenAI API 兼容的云侧视觉模型。

OpenAI API 兼容配置示例：

```json
{
  "backend": "openai_compatible",
  "openai_base_url": "https://your-provider.example/v1",
  "openai_model_name": "your-text-model",
  "openai_vision_model_name": "your-vision-model",
  "openai_api_key": "your-api-key"
}
```

### 配置文件

持久配置文件位于 `~/.texada/config.json`。

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

| 环境变量 | 用途 |
|----------|------|
| `TEXADA_OLLAMA_HOST` | 本地 Ollama 地址，支持自定义端口 |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI 监听地址 |
| `TEXADA_WEB_HOST`, `TEXADA_WEB_PORT` | 本地浏览器启动地址 |
| `TEXADA_API_BASE` | 桌面壳使用的完整 API 地址 |
| `TEXADA_API_TIMEOUT_SECS` | 桌面端 API 请求超时时间 |

### 从源码运行

```bash
git clone https://github.com/CacinieP/TeXada-the-Math-Agent.git
cd TeXada-the-Math-Agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
texada check
./start.sh
```

macOS 上也可以双击 `TeXada.command`，它会启动同一套本地 API 和 Web UI。

### 桌面端构建

GitHub Actions 会从 `main` 和版本 tag 构建安装包。

| Workflow | 检查内容 |
|----------|----------|
| `Audit` | Ruff、pytest、pip-audit、npm audit、JS 语法检查、macOS/Windows Tauri cargo check |
| `Desktop Release` | 预发布审计、签名 macOS arm64/Intel DMG、Windows x64 NSIS 安装器 |

Windows 本地构建辅助脚本：

```powershell
cargo install tauri-cli --version "^2" --locked
.\scripts\build-windows-app.ps1
```

macOS release 签名需要以下 GitHub Secrets：

| Secret | 用途 |
|--------|------|
| `APPLE_CERTIFICATE` | base64 编码的 `.p12` 证书 |
| `APPLE_CERTIFICATE_PASSWORD` | `.p12` 导出密码 |
| `APPLE_SIGNING_IDENTITY` | 签名身份，例如 `Yichun Deng` |
| `APPLE_TEAM_ID` | Apple Team ID |

workflow 会签名并验证 DMG。Notarization 是单独步骤，需要 Developer ID/notary 凭据。

### 快捷键

| 操作 | 快捷键 |
|------|--------|
| 显示或隐藏浮窗 | macOS `Option+Command+T`，Windows `Ctrl+Alt+T` |
| 切换渲染模式 | macOS `Command+K`，Windows `Ctrl+K` |
| 放大 | `Command/Ctrl + +` |
| 缩小 | `Command/Ctrl + -` |
| 重置缩放 | `Command/Ctrl + 0` |
| 移动窗口 | 拖动标题栏 |

### 硬件与实测

下面是 2026-07-07 的本地实测，不是合成跑分。响应时间会受模型大小、量化方式、机器负载和模型是否已预热影响。

实测环境：macOS 26.5.1，arm64，Apple A18 Pro，8GB RAM，本地 Ollama 模型。

| 场景 | 推荐硬件 |
|------|----------|
| 文本转换和补全 | Apple Silicon、Intel i5/Ryzen 5 或更高，8GB RAM |
| 常用截图 OCR | Apple Silicon M2/M3 级别或更高，16GB RAM |
| 高频 OCR 或更大模型 | 16GB+ RAM、独立 GPU，或云侧视觉模型 |

| 操作 | 模型 | 实测响应 |
|------|------|----------|
| NL 转 LaTeX，冷启动 | MiniCPM5-1B | 179204.3ms |
| NL 转 LaTeX，预热后 | MiniCPM5-1B | 29612.2ms |
| LaTeX 补全 | MiniCPM5-1B 加规则 | 1808.5ms |
| OCR 示例 | MiniCPM-V 4.6 | 39419.0ms |

### 质量门禁

当前 `main` 分支在最新审计后没有已知阻塞问题。这里的含义是测试和静态检查通过，不是声称软件绝对不可能有 bug。

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uvx pip-audit --strict
npm ci
npm audit --audit-level=moderate
node --check tauri-shell/src/main.js
cd tauri-shell/src-tauri && cargo check
```

### 文档

- [架构文档](docs/architecture.md)
- [源码审计](docs/audit.md)
- [技术报告](TECHNICAL_REPORT.md)

### 开源协议

TeXada-the-Math-Agent 使用 `GPL-3.0-or-later` 协议发布，详见 [LICENSE](LICENSE)。

</details>
