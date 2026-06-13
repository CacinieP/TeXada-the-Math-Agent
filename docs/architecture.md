# TeXada — 技术架构

> **版本**: v0.3.0 · 纯 Ollama 后端
> **核心**: 端侧 MiniCPM(文本 + 视觉),零云端依赖

TeXada 把自然语言、LaTeX 片段、公式图片统一转换成 LaTeX,并即时渲染、校验、自动修复。本文描述**当前实现**架构。早期设计思路见 [`design.md`](design.md)(历史稿)。

---

## 1. 系统概览

```
┌──────────────────────────────────────────────────────┐
│            用户(浏览器 / macOS .app 壳)              │
│           http://127.0.0.1:5173  (静态前端)          │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP / fetch (CORS *)
┌────────────────────────▼─────────────────────────────┐
│           FastAPI 后端  127.0.0.1:18732               │
│                                                       │
│   api.py ──► InputRouter ──► 确定性管线               │
│    (HTTP)     (路由)        intent · symbols          │
│                              validator · fixer        │
│                                   │                   │
│                   ┌───────────────┴────────────┐      │
│                   ▼                            ▼      │
│             MiniCPMModel              RenderEngine    │
│             (NL/补全/OCR)             (KaTeX/高亮)    │
│                   │                                   │
│             BackendManager ── 就绪检测/自动拉起       │
└───────────────────┼──────────────────────────────────┘
                    │ OpenAI 兼容  /v1/chat/completions
         ┌──────────▼──────────┐
         │   Ollama daemon     │
         │  :11434             │
         │  MiniCPM5-1B (文本) │
         │  MiniCPM-V 4.6 (视觉)│
         └─────────────────────┘
```

**两层职责**:
- **确定性层**(代码):意图分类、符号预翻译、LaTeX 校验/修复、缩写、渲染 —— 零模型,毫秒级。
- **模糊层**(模型):NL→LaTeX、OCR —— MiniCPM via Ollama。

---

## 2. 后端组件 (`src/texada/`)

| 模块 | 职责 |
|------|------|
| `config.py` | Pydantic Settings,从 `~/.texada/config.json` + `TEXADA_` 环境变量加载(模型/host/渲染/热键/历史)。 |
| `__main__.py` | Typer CLI:`serve` / `convert` / `check`。 |
| `api.py` | FastAPI 工厂。端点:`/api/status` `/convert` `/ocr` `/complete` `/validate` `/shorthands` `/history` `/render-mode`。转换成功后写服务端 history。 |
| `core/router.py` | `InputRouter`:按输入类型/内容路由到 NL→LaTeX / 补全 / OCR / 缩写管线,维护会话记忆。 |
| `core/backend.py` | `BackendManager`:Ollama 就绪检测(`/v1/models`)+ 未运行时 `ollama serve` 自动拉起 + 检查模型已 pull。**零 ollama 包依赖**(httpx + subprocess)。 |
| `core/model.py` | `MiniCPMModel`:OpenAI 兼容 chat 调用,NL→LaTeX / 补全(规则优先)/ OCR(多模态)。reasoning 字段回退;`trust_env=False` 绕过系统代理。 |
| `core/intent.py` | 规则意图分类(integral / derivative / sum / limit / matrix / probability / generic)。 |
| `core/symbols.py` | 符号预翻译(「积分」→ `\int` 等),降低模型负担。 |
| `core/validator.py` · `fixer.py` | LaTeX 语法校验 + 自动修复(括号匹配等)。 |
| `core/ocr.py` | OCR 管线:OpenCV 预处理 → MiniCPM-V 多模态推理。 |
| `core/prompts.py` | system / few-shot / OCR / 补全 prompt。NL 强调「忠实直译」。 |
| `render/engine.py` | 双模式:KaTeX(`npx katex` subprocess)+ 纯 LaTeX 高亮。 |
| `store/shorthand.py` | 缩写库(内置 + 自定义)。**全后端共享单例**(router 与 `/api/shorthands` 同一实例)。 |
| `store/history.py` | SQLite 历史,自动清理。 |
| `platform/` | macOS / Windows 剪贴板与平台适配。 |

---

## 3. 模型层(纯 Ollama)

**单一后端**:Ollama daemon(`localhost:11434`),暴露 OpenAI 兼容 `/v1` 端点。推理层(`MiniCPMModel`)全程用 `openai` SDK,**不依赖 ollama 原生包** —— 这也是 `backend.py` 的健康检查对任何 OpenAI 兼容后端都通用的原因。

| 角色 | 模型 tag | 用途 |
|------|---------|------|
| 文本 | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | NL→LaTeX、补全 |
| 视觉 | `openbmb/minicpm-v4.6:latest` | OCR(多模态 `image_url`) |

**关键决策**:
- MiniCPM5 是**推理模型**,答案常在 `reasoning` 字段而 `content` 为空 —— `generate_latex` / `complete_latex` 都做 reasoning 回退;`max_tokens` 需 ≥ 2048(256 会把 token 全耗在思维链上,`content` 被截断为空)。
- 本地连接 `httpx(trust_env=False)` / openai `http_client`,避免系统代理劫持 localhost(否则 `/api/status` 误报 `not_running`)。
- `backend.py` 用 `/v1/models` 探活 + 列模型,字符串匹配检查模型是否已 pull。

---

## 4. 补全策略:规则优先 + 模型兜底

MiniCPM5-1B 对「补全任意 LaTeX 片段」不可靠(常输出空括号)。`complete_latex` 采用:

1. **规则优先**:`_RULE_COMPLETIONS` 精确后缀匹配高频片段 —— 零延迟、零误差。
   - `\sum_{i=1}^{` → `\sum_{i=1}^{n} x_i`
   - `\int` → `\int_{0}^{1} f(x)\,dx`
   - `\frac{` → `\frac{}{}`、`\sqrt{` → `\sqrt{}`、`\lim` → `\lim_{x \to 0}`、`\mathbb{` → `\mathbb{R}` 等
2. **模型兜底**:规则未命中才调 MiniCPM5,处理任意片段。

---

## 5. 数据流

| 路由 | 流程 |
|------|------|
| **NL→LaTeX** | router → intent 分类 → symbol 预翻译 → MiniCPM5 `generate_latex`(few-shot + 会话记忆)→ validator/fixer → render |
| **补全** | router → `complete_latex`(**规则优先**,模型兜底)→ validator → render |
| **OCR** | router → OpenCV 预处理 → MiniCPM-V `ocr_latex` → validator → render |
| **缩写** | router → `shorthand_store` 精确匹配 → render(**零模型**) |

所有管线共享 `_validate_and_fix`(校验 + 自动修复)与 `_render`(KaTeX / 纯 LaTeX,⌘K 切换)。

---

## 6. 前端 (`tauri-shell/src/`)

纯静态(HTML + IIFE JS + CSS),**无构建步骤**。CDN 加载 KaTeX 做浏览器端渲染;`main.js` 通过 fetch 调后端 API。

- 顶部 `tab-bar`:NL / OCR / 补全 / 缩写 / 历史 / 设置(数字键 1–6 切换)。
- 缩写搜索框:本地按 key/value 过滤(数据全量加载)。
- 历史:优先读 `/api/history`,后端不可用回退 localStorage。
- 渲染:浏览器端 KaTeX(后端 `katex_html` 字段作为兜底)。

---

## 7. 运行与部署

| 方式 | 说明 |
|------|------|
| **双击 `TeXada.app`** | macOS 桌面应用:后台启动 API + 前端(持久),打开浏览器 + 系统通知,无终端窗口 |
| 双击 `TeXada.command` | 同上但在终端运行,可看实时日志 |
| `texada serve` | 仅启动 API |
| `start.sh` | 启动 API + Swift 浮窗(macOS) |
| `texada check` | 就绪检查(Ollama、模型) |

**`TeXada.app` 机制**:`MacOS/TeXada`(bash)检测服务是否已在跑 → 拉起 Ollama(若需)→ `nohup ... & disown` 启动 API 与前端(**脱离 launcher,持久运行**)→ 开浏览器 + 通知 → launcher 退出,服务继续。日志在 `logs/`。

**依赖**:Python 3.12+、Ollama、(可选)Node/npx —— 后端 KaTeX 渲染用;前端 KaTeX 走 CDN 不强制。

**配置**:`~/.texada/config.json`(模型 tag、host、`max_tokens`、渲染模式等),`TEXADA_` 前缀环境变量可覆盖。

---

## 8. 目录结构

```
TeXada-the-Math-Agent/
├── src/texada/           # Python 包
│   ├── config.py · api.py · __main__.py · types.py
│   ├── core/    # router · backend · model · intent · symbols
│   │            # validator · fixer · ocr · prompts
│   ├── render/  # engine(KaTeX) · highlighter
│   ├── store/   # shorthand · history
│   └── platform/# macos · windows
├── tests/               # pytest(单元 + e2e)
├── tauri-shell/src/     # 静态前端(index.html · main.js · style.css)
├── docs/                # architecture(本文) · design(历史) · ui-mockup
├── TeXada.app/          # macOS 桌面应用包(Info.plist · MacOS/TeXada · Resources/AppIcon.icns)
├── TeXada.command       # macOS 双击启动(终端版,看日志)
├── assets/              # TeXada.icns 图标源(iconset 中间产物 .gitignore)
├── logs/                # 运行日志(api/web/launcher/ollama,.gitignore)
├── start.sh · README.md · TECHNICAL_REPORT.md · pyproject.toml
└── dist/                # 构建产物(.gitignore)
```

---

## 9. 演进

- **v0.1–0.2**:llama.cpp 双实例 + 早期 Gemma 评估(见 `docs/design.md` 历史稿)。
- **v0.3**:纯 Ollama 后端 + MiniCPM5-1B / MiniCPM-V 4.6 + 补全规则兜底 + 代理修复 + `TeXada.command` 点击即启动。
