# TeXada 技术报告

## 1. 模型选型

### 为什么选择 Gemma 4 E4B（4B Efficient）？

| 考量维度 | Gemma 4 E4B | Gemma 4 26B MoE | Gemma 4 31B Dense |
|---------|------------|----------------|-------------------|
| 原生函数调用 | ✅ 完整支持 | ✅ 支持 | ✅ 支持 |
| 端侧推理速度 | ~40 tok/s (M1) | ~12 tok/s | ~8 tok/s |
| 离线运行 | ✅ 单机 Ollama | 需 >16GB VRAM | 需 >24GB VRAM |
| 多模态 OCR | ✅ E4B 视觉变体 | ✅ | ✅ |
| QAT 量化精度 | ✅ INT4 无损 | ✅ | ✅ |

**核心决策理由**：
1. **延迟是 UX 生命线**：TeXada 定位为「即输即得」的浮动公式面板，端到端延迟必须 <2s。E4B 在 M1 MacBook Air 上可达到 ~40 tok/s，而 26B MoE 约 12 tok/s——三倍差距直接决定产品可用性。
2. **原生函数调用（Native Function Calling）是关键差异化**：Gemma 4 原生支持 OpenAI 兼容的 `tools` schema，无需 prompt hack 即可让模型主动调用 `validate_latex` 和 `lookup_symbol`。E4B 在 function calling 准确率上与更大模型差距 <5%，但延迟优势显著。
3. **完全离线部署**：TeXada 的用户场景（学术会议、课堂、论文写作）经常处于无网络环境。E4B 的 QAT（Quantization-Aware Training）变体在 INT4 精度下保持 function calling 能力，单机即可运行。

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend Layer                        │
│  Swift WKWebView (macOS)  /  Tauri (cross-platform)     │
│  ⌥⌘T 唤醒 → 输入 → 实时渲染 → 一键复制                   │
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
│  │           Gemma 4 E4B (via Ollama)                │  │
│  │                                                    │  │
│  │  Tools: [validate_latex, lookup_symbol]            │  │
│  │  Memory: ConversationMemory (6 turns)              │  │
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
│  │ (JSON)       │  │ (SQLite)     │  │ (platform)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 2.2 核心模块设计

#### InputRouter — 路由 + Agent Memory + Tool Calling 循环

```
用户输入 → route(tab, content) → [shorthand | completion | nl2latex | ocr]
                                            │
                        ┌───────────────────┘
                        ▼
              nl2latex 管线:
              1. IntentClassifier.classify(text)    → intent, confidence
              2. SymbolEngine.pre_translate(text)    → 中文术语 → LaTeX 符号
              3. Gemma4E4B.generate_latex(           → Tool Calling 循环
                   preprocessed,
                   intent,
                   memory=ConversationMemory.to_messages(),
                   tools=[validate_latex, lookup_symbol]
                 )
              4. LaTeXValidator.validate(latex)       → 结构化检查
              5. LaTeXFixer.fix(latex, errors)        → 自动修复
              6. RenderEngine.render(latex)            → KaTeX HTML / 高亮
              7. ConversationMemory.add(turn)          → 存入 Agent Memory
```

#### Native Function Calling 实现细节

```python
# tool schemas (OpenAI-compatible, Gemma 4 原生支持)
LATEX_TOOLS = [
    {"type": "function", "function": {
        "name": "validate_latex",
        "parameters": {"latex": {"type": "string"}}
    }},
    {"type": "function", "function": {
        "name": "lookup_symbol",
        "parameters": {"term": {"type": "string"}}
    }},
]

# Agent loop (max 2 iterations)
response = client.chat(model="gemma4:e4b-it-qat", messages=..., tools=LATEX_TOOLS)
while response.message.tool_calls:
    for tc in response.message.tool_calls:
        result = tool_handlers[tc.name](**tc.arguments)  # 本地执行
    response = client.chat(messages + tool_results, tools=LATEX_TOOLS)  # 继续生成
```

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
| 自然语言 → LaTeX | Gemma 4 E4B | ✅ |
| OCR 图片识别 | Gemma 4 E4B 视觉 | ✅ |

这意味着 **90% 的请求路径零模型调用**，只有在真正需要语义理解时才启动模型推理。

---

## 3. 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 快捷公式查找 | <1ms | JSON 字典查询 |
| 意图识别 | <1ms | 正则匹配 |
| 符号预翻译 | <5ms | ~130 个术语的 regex 替换 |
| NL→LaTeX (shorthand 命中) | <1ms | 零模型调用 |
| NL→LaTeX (模型推理) | 1-3s | 取决于是否触发 Tool Calling |
| OCR 图片识别 | 2-4s | OpenCV 预处理 + E4B 多模态推理 |
| 渲染切换 (⌘K) | <1ms | 缓存重渲染，零模型调用 |

---

## 4. 技术亮点

### 4.1 Agent Memory

```python
class ConversationMemory:
    """Per-session context — keeps last 6 turns."""
    def add(self, turn: ConversationTurn): ...
    def to_messages(self) -> list[dict]: ...
```

- 每次请求注入历史对话上下文，模型可理解 "把它改成定积分" 等后续指令
- 包含完整的 Tool Calling 历史（assistant 的 tool_calls + tool 的 results）

### 4.2 Tool Calling 循环

模型在生成 LaTeX 过程中可主动调用工具：
- `validate_latex`: 验证生成的 LaTeX 语法，发现错误可自行修正
- `lookup_symbol`: 查询中文数学术语的 LaTeX 等价符号

这不是 prompt engineering，而是结构化的 Agent 循环。

### 4.3 多层验证 + 自动修复

```
模型输出 → LaTeXValidator (括号/环境/命令/KaTeX) → LaTeXFixer (自动修复)
```

验证器检查四层：括号平衡、环境配对、命令有效性、KaTeX 渲染。修复器可自动补全缺失的括号和环境闭合标签。

---

## 5. 已知局限与未来方向

| 局限 | 计划改进 |
|------|---------|
| E4B 在复杂矩阵推导上偶有错误 | 升级到 26B MoE 作为可选高质量模式 |
| OCR 对手写体识别率有限 | 增加手写体训练数据微调 |
| 无 Windows GUI shell | 开发 Tauri 跨平台 shell |
| Agent Memory 仅限单次会话 | 添加持久化对话存储 |

---

*TeXada Team — Gemma 4 Developer Hackathon 2026*
