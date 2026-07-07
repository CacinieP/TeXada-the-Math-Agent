# TeXada 技术报告

## 1. 模型选型

### 为什么选择 MiniCPM？

| 考量维度 | MiniCPM5-1B (文本) | MiniCPM-V 4.6 (视觉) |
|---------|-------------------|---------------------|
| 参数量 | 1B | 752M (+ 504M projector) |
| 推理速度 | 极快（1B 参数） | 快（轻量多模态） |
| 离线运行 | ✅ Ollama 本地 | ✅ Ollama 本地 |
| 多模态 OCR | ❌ 纯文本 | ✅ 视觉+文本 |
| API 兼容 | OpenAI Chat Completions | OpenAI Chat Completions |

**核心决策理由**：
1. **极低延迟**：MiniCPM5-1B 仅 1B 参数，在 CPU/轻量 GPU 上即可达到极快推理速度，满足「即输即得」的 UX 要求。
2. **双模型架构**：文本推理用 MiniCPM5-1B，OCR 用 MiniCPM-V 4.6；二者默认由 Ollama 的 OpenAI-compatible `/v1` 端点统一提供。
3. **OpenAI-compatible 抽象**：本地 Ollama 与云侧 provider 走同一套 Chat Completions 调用，设置页可切换 endpoint / model / vision model / key。
4. **默认离线**：TeXada 可完全通过本地 Ollama 运行；只有用户显式切到 OpenAI-compatible 云侧后端时才会访问云端。

### 架构决策：移除 Native Function Calling

MiniCPM 不支持 Gemma 4 的原生 `tools` schema。替代方案：
- **后处理验证**：`LaTeXValidator` + `LaTeXFixer` 在模型输出后自动检查和修复，无需模型参与
- **确定性预翻译**：`SymbolEngine` 在推理前将中文术语替换为 LaTeX 符号，减少模型负担
- 这些确定性模块的覆盖率已超过 90%，模型只需处理真正需要语义理解的部分

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend Layer                        │
│  Tauri desktop shell / browser development UI           │
│  ⌥⌘T / Ctrl+Alt+T 唤醒 → 渲染 → 复制或光标处键入          │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP API
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI Backend (Python)                 │
│                                                          │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐  │
│  │ Intent   │  │ Symbol    │  │ InputRouter          │  │
│  │ Classifier│  │ Engine    │  │ (Memory + Routing)   │  │
│  │ (regex)  │  │ (dict)    │  │                      │  │
│  └────┬─────┘  └─────┬────┘  └──────────┬───────────┘  │
│       │              │                   │               │
│  ┌────▼──────────────▼───────────────────▼───────────┐  │
│  │     MiniCPM5-1B (Ollama /v1, 文本)               │  │
│  │     MiniCPM-V 4.6 (Ollama /v1, 视觉)             │  │
│  │     OpenAI-compatible cloud models (可选)        │  │
│  │                                                    │  │
│  │  Few-shot examples + deterministic guards           │  │
│  │  Few-shot: intent-specific examples                │  │
│  └────────────────────┬───────────────────────────────┘  │
│                       │                                  │
│  ┌────────────────────▼───────────────────────────────┐  │
│  │            Post-processing Pipeline                │  │
│  │                                                    │  │
│  │  LaTeXValidator → LaTeXFixer → RenderEngine        │  │
│  │  (brace/env/cmd)   (auto-repair)  (KaTeX/pure)    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ ShorthandStore│  │ HistoryStore │  │ Clipboard    │  │
│  │ (built-in+db) │  │ (SQLite)     │  │ (platform)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 2.2 核心模块设计

#### InputRouter — 路由 + 确定性防漂移

```
用户输入 → route(tab, content) → [shorthand | completion | nl2latex | ocr]
                                            │
                        ┌───────────────────┘
                        ▼
              nl2latex 管线:
              1. IntentClassifier.classify(text)    → intent, confidence
              2. SymbolEngine.pre_translate(text)    → 中文术语 → LaTeX 符号
              3. MiniCPMModel.generate_latex(        → OpenAI-compatible chat 推理
                   preprocessed,
                   intent
                 )
              4. LaTeXValidator.validate(latex)       → 结构化检查
              5. LaTeXFixer.fix(latex, errors)        → 自动修复
              6. RenderEngine.render(latex)            → KaTeX HTML / 高亮
              7. HistoryStore.add(turn)                → 服务端历史
```

#### OpenAI 兼容 API 调用

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
response = client.chat.completions.create(
    model="hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M",
    messages=[{"role": "system", "content": SYSTEM_PROMPT}, ...],
    temperature=0.1,
    max_tokens=2048,
)
```

`http://localhost:11434` 只是 Ollama 默认地址；实际地址来自设置页、
`~/.texada/config.json` 的 `ollama_host`，或 `TEXADA_OLLAMA_HOST`。

### 2.3 确定性优先策略

TeXada 的核心设计原则：**能用确定性代码解决的问题，绝不调用模型**。

| 功能 | 实现方式 | 模型调用 |
|------|---------|---------|
| 意图识别 | 正则匹配（<1ms） | ❌ |
| 中文术语翻译 | 字典替换（按长度优先） | ❌ |
| 快捷公式查找 | JSON 键值查询 | ❌ |
| LaTeX 语法验证 | 括号/环境/命令检查 | ❌ |
| 自动修复 | 规则引擎（补全括号等） | ❌ |
| 渲染 | KaTeX CLI / 语法高亮 | ❌ |
| 自然语言 → LaTeX | MiniCPM5-1B | ✅ |
| OCR 图片识别 | MiniCPM-V 4.6 视觉 | ✅ |

这意味着 **90% 的请求路径零模型调用**，只有在真正需要语义理解时才启动模型推理。

---

## 3. 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 快捷公式查找 | <1ms | JSON 字典查询 |
| 意图识别 | <1ms | 正则匹配 |
| 符号预翻译 | <5ms | ~130 个术语的 regex 替换 |
| NL→LaTeX (shorthand 命中) | <1ms | 零模型调用 |
| NL→LaTeX (模型推理) | 冷启动 179204.3ms；warm 29612.2ms | 2026-07-07，Apple A18 Pro / 8GB RAM / Ollama |
| OCR 图片识别 | 39419.0ms | 2026-07-07，MiniCPM-V 4.6 样例图 |
| 渲染切换 (⌘K) | <1ms | 缓存重渲染，零模型调用 |

---

## 4. 技术亮点

### 4.1 独立请求防漂移

- NL→LaTeX 不再把上一条模型输出注入下一条独立请求，避免无关公式被复用。
- 交互历史仍写入服务端 `HistoryStore` 和前端 history，用于回看与再次插入。

### 4.2 多层验证 + 自动修复

```
模型输出 → LaTeXValidator (括号/环境/命令/KaTeX) → LaTeXFixer (自动修复)
```

验证器检查四层：括号平衡、环境配对、命令有效性、KaTeX 渲染。修复器可自动补全缺失的括号和环境闭合标签。

### 4.3 双模型架构

- **文本推理**：MiniCPM5-1B on Ollama `/v1`，专注 NL→LaTeX / 补全
- **视觉 OCR**：MiniCPM-V 4.6 on Ollama `/v1`，处理图片输入；也可配置 MiniCPM5-1B 系兼容视觉模型
- **云侧模型**：任意 OpenAI API 兼容 provider，设置页填写 endpoint / model / vision model / API key

### 4.4 桌面交互

- 顶部标题栏调用 Tauri `start_dragging`，可拖动浮窗位置。
- 设置页支持 80% 到 140% UI 缩放，快捷键为 `Cmd/Ctrl + +`、`Cmd/Ctrl + -`、`Cmd/Ctrl + 0`。
- 点击公式块会在系统当前光标处键入公式；复制按钮保持复制语义。

---

## 5. 已知局限与未来方向

| 局限 | 计划改进 |
|------|---------|
| 1B 模型在复杂矩阵推导上偶有错误 | 可选切换更大 OpenAI-compatible 模型 |
| OCR 对手写体识别率有限 | 增加手写体训练数据微调 |
| macOS 点击公式插入需要辅助功能权限 | 首次使用时在系统设置授权 TeXada |
| 未接入 Apple notarization | 先签名并校验 Yichun Deng 证书，后续可补 notarization secrets |

---

*TeXada v0.3.0 — MiniCPM Migration*
