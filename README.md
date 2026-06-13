# TeXada — Math Formula Agent

> 端侧数学公式 Agent，基于 **MiniCPM** 系模型，通过 **Ollama** 本地推理，零云端依赖。

TeXada 把自然语言、LaTeX 片段、手写公式图片统一转换成 LaTeX，并即时渲染（KaTeX / LaTeX 高亮）、校验、自动修复。双模型各司其职：

| 角色 | 模型 | 用途 |
|------|------|------|
| 文本推理 | **MiniCPM5-1B** (`hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M`) | 自然语言 → LaTeX、LaTeX 补全 |
| 视觉 OCR | **MiniCPM-V 4.6** (`openbmb/minicpm-v4.6:latest`) | 手写 / 截图公式识别 |

两个模型都跑在同一个本地 **Ollama** daemon 上（Ollama 提供 OpenAI 兼容的 `/v1` 端点，推理层直接复用标准 OpenAI Chat API）。

## 特性

- 🧮 **自然语言 → LaTeX**：「二重积分 f(x,y) 在区域 D 上」→ `\iint_D f(x,y)\,dx\,dy`
- ✍️ **LaTeX 补全**：`\sum_{i=1}^{` → `\sum_{i=1}^{n} x_i`
- 📷 **OCR 图片识别**：MiniCPM-V 多模态识别手写 / 截图公式
- ⚡ **快捷公式**：输入 `euler` → `e^{i\pi}+1=0`（可自定义）
- ✅ **自动校验 + 修复**：LaTeX 语法检查，错误自动尝试修复
- 🔒 **完全离线**：本地 Ollama，无任何云端调用

## 快速启动（macOS 双击）

完成下方「快速开始」的安装后，项目根的 **`TeXada.command`** 可双击一键启动 —— 自动拉起 API + 前端并打开浏览器：

1. 在 Finder 双击 `TeXada.command`（首次运行可能需 **右键 → 打开** 以绕过 Gatekeeper）。
2. 终端窗口显示启动日志，浏览器自动打开 http://127.0.0.1:5173/。
3. 关闭终端窗口或按 `Ctrl+C` 即停止全部服务。

> 脚本会自动检测并尝试启动 Ollama（若未运行）。

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
TeXada v0.2.0 — System Check
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
texada serve          # 启动 FastAPI 后端 (http://127.0.0.1:18732)
# 或一键启动（含 macOS Swift 浮窗）：
./start.sh
```

## 配置

配置从 `~/.texada/config.json` 读取（也可用 `TEXADA_` 前缀环境变量覆盖）：

```json
{
  "ollama_host": "http://localhost:11434",
  "model_name": "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
  "vision_model_name": "openbmb/minicpm-v4.6:latest",
  "max_tokens": 2048,
  "default_render_mode": "katex"
}
```

> `max_tokens` 建议 ≥ 2048 —— MiniCPM5 是推理模型，思维链需要空间。

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
