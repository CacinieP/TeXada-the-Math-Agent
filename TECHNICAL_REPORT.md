# TeXada 技术报告

## 1. 模型选型

### 为什么选择 MiniCPM？

| 考量维度 | MiniCPM5-1B (文本) | MiniCPM-V 4.6 (视觉) |
|---------|-------------------|---------------------|
| 参数量 | 1B | 752M (+ 504M projector) |
| 推理速度 | 极快（1B 参数） | 快（轻量多模态） |
| 离线运行 | ✅ llama.cpp 单机 | ✅ llama.cpp 单机 |
| 多模态 OCR | ❌ 纯文本 | ✅ 视觉+文本 |
| API 兼容 | OpenAI Chat Completions | OpenAI Chat Completions |

**核心决策理由**：
1. **极低延迟**：MiniCPM5-1B 仅 1B 参数，在 CPU/轻量 GPU 上即可达到极快推理速度，满足「即输即得」的 UX 要求。
2. **双模型架构**：文本推理用 MiniCPM5-1B（`localhost:8080`），OCR 用 MiniCPM-V 4.6（`localhost:8081`），各司其职，互不干扰。
3. **llama.cpp 部署**：使用 llama.cpp 的 OpenAI 兼容 API，无需 Ollama 等额外运行时，直接 GGUF 模型文件加载。
4. **完全离线**：TeXada 的用户场景（学术会议、课堂、论文写作）经常处于无网络环境，llama.cpp 单机部署天然支持。

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
│  │     MiniCPM5-1B (llama.cpp :8080, 文本)           │  │
│  │     MiniCPM-V 4.6 (llama.cpp :8081, 视觉)        │  │
│  │                                                    │  │
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

#### InputRouter — 路由 + Agent Memory

```
用户输入 → route(tab, content) → [shorthand | completion | nl2latex | ocr]
                                            │
                        ┌───────────────────┘
                        ▼
              nl2latex 管线:
              1. IntentClassifier.classify(text)    → intent, confidence
              2. SymbolEngine.pre_translate(text)    → 中文术语 → LaTeX 符号
              3. MiniCPMModel.generate_latex(        → 纯 chat 推理
                   preprocessed,
                   intent,
                   memory=ConversationMemory.to_messages()
                 )
              4. LaTeXValidator.validate(latex)       → 结构化检查
              5. LaTeXFixer.fix(latex, errors)        → 自动修复
              6. RenderEngine.render(latex)            → KaTeX HTML / 高亮
              7. ConversationMemory.add(turn)          → 存入 Agent Memory
```

#### OpenAI 兼容 API 调用

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="sk-no-key")
response = client.chat.completions.create(
    model="MiniCPM5-1B",
    messages=[{"role": "system", "content": SYSTEM_PROMPT}, ...],
    temperature=0.1,
    max_tokens=256,
)
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
| NL→LaTeX (模型推理) | 0.5-2s | 1B 参数，极快推理 |
| OCR 图片识别 | 2-4s | OpenCV 预处理 + MiniCPM-V 多模态推理 |
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

### 4.2 多层验证 + 自动修复

```
模型输出 → LaTeXValidator (括号/环境/命令/KaTeX) → LaTeXFixer (自动修复)
```

验证器检查四层：括号平衡、环境配对、命令有效性、KaTeX 渲染。修复器可自动补全缺失的括号和环境闭合标签。

### 4.3 双模型架构

- **文本推理**：MiniCPM5-1B on `:8080` — 极快的 1B 参数模型，专注 NL→LaTeX
- **视觉 OCR**：MiniCPM-V 4.6 on `:8081` — 轻量多模态模型，处理图片输入
- 两个 llama.cpp 实例独立运行，互不干扰

---

## 5. 已知局限与未来方向

| 局限 | 计划改进 |
|------|---------|
| 1B 模型在复杂矩阵推导上偶有错误 | 可选切换更大模型（MiniCPM-V 4.6 或外部模型） |
| OCR 对手写体识别率有限 | 增加手写体训练数据微调 |
| 无 Windows GUI shell | 开发 Tauri 跨平台 shell |
| Agent Memory 仅限单次会话 | 添加持久化对话存储 |

---

*TeXada v0.3.0 — MiniCPM Migration*
