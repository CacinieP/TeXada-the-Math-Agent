# TeXada — 技术架构文档

> **版本**: v2.0
> **日期**: 2026-06-08
> **核心约束**: 端侧运行 Gemma 4 E4B，零云端依赖
> **目标平台**: macOS (Apple Silicon) + Windows (x64/ARM64)

---

## 0. 设计原则

1. **确定性优先，LLM 兜底** — 符号查找、模板填充、语法校验由代码完成；LLM 只处理 NL→LaTeX 的模糊映射
2. **窄域深做** — 只做 LaTeX 公式生成与操作，不做通用数学助手
3. **单轮快出** — temperature=0.1 + max_tokens=256，让 E4B 一次出对
4. **渐进增强** — 基础功能零模型可用，E4B 加持后升级
5. **双平台原生** — macOS 菜单栏 + Windows 系统托盘，共享 Python 后端
6. **双渲染模式** — KaTeX 视觉渲染 + 纯 LaTeX 语法高亮，⌘K 即时切换

---

## 1. 系统全景

### 1.1 架构总图

```
┌──────────────────────────────────────────────────────────────────────┐
│                        TeXada System                                 │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Platform Shell (原生)                        │ │
│  │  ┌──────────────────┐    ┌──────────────────────┐             │ │
│  │  │  macOS Menu Bar  │    │  Windows System Tray │             │ │
│  │  │  (Swift/ObjC)    │    │  (Python pystray)    │             │ │
│  │  └────────┬─────────┘    └──────────┬───────────┘             │ │
│  │           └──────────┬──────────────┘                          │ │
│  │                      ▼                                          │ │
│  │           ┌─────────────────────┐                               │ │
│  │           │   Popover Window   │                               │ │
│  │           │   (WebView / Tk)   │  ← 6-Tab UI                  │ │
│  │           │   ⌥⌘T / Win+T     │                               │ │
│  │           └─────────┬───────────┘                             │ │
│  └─────────────────────┼──────────────────────────────────────────┘ │
│                        │ IPC (HTTP localhost:18732)                 │
│  ┌─────────────────────▼──────────────────────────────────────────┐ │
│  │                  Python Backend (FastAPI)                       │ │
│  │                                                                │ │
│  │  ┌───────────┐  ┌──────────┐  ┌──────────────┐               │ │
│  │  │  Input    │  │  Intent  │  │  Pipeline    │               │ │
│  │  │  Router   │─▶│  Class.  │─▶│  Dispatcher  │               │ │
│  │  └───────────┘  └──────────┘  └──────┬───────┘               │ │
│  │                                       │                        │ │
│  │            ┌──────────────────────────┼────────────┐          │ │
│  │            │                          │            │          │ │
│  │      ┌─────▼──────┐  ┌───────────────▼─────┐  ┌──▼────────┐ │ │
│  │      │  Symbol    │  │   Gemma 4 E4B      │  │  Shorthand │ │ │
│  │      │  Engine    │  │   (Ollama API)      │  │  Store     │ │ │
│  │      │  (零模型)  │  │                     │  │  (零模型)  │ │ │
│  │      └─────┬──────┘  └─────────┬───────────┘  └──┬────────┘ │ │
│  │            │                   │                  │          │ │
│  │      ┌─────▼───────────────────▼──────────────────▼────┐     │ │
│  │      │              Render Engine                       │     │ │
│  │      │  ┌─────────────────┐  ┌──────────────────────┐ │     │ │
│  │      │  │  KaTeX Renderer  │  │  LaTeX Syntax         │ │     │ │
│  │      │  │  (视觉公式渲染)  │  │  Highlighter          │ │     │ │
│  │      │  │  output: html    │  │  (结构高亮拆解)       │ │     │ │
│  │      │  │  copy: $$...$$   │  │  output: highlighted  │ │     │ │
│  │      │  │                  │  │  copy: 裸 LaTeX       │ │     │ │
│  │      │  └─────────────────┘  └──────────────────────┘ │     │ │
│  │      └──────────────────────────┬──────────────────────┘     │ │
│  │                                 │                             │ │
│  │      ┌──────────────────────────▼──────────────────────┐     │ │
│  │      │            Validation Layer                      │     │ │
│  │      │  brace balance · env balance · command check    │     │ │
│  │      │  KaTeX parse · LaTeX Fixer (自动修复)           │     │ │
│  │      └──────────────────────────┬──────────────────────┘     │ │
│  │                                 │                             │ │
│  │      ┌──────────────────────────▼──────────────────────┐     │ │
│  │      │            Output Adapter                         │     │ │
│  │      │  Clipboard · Editor Insert · HTTP API             │     │ │
│  │      └──────────────────────────────────────────────────┘     │ │
│  │                                                               │ │
│  │  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐   │ │
│  │  │  History       │  │  Template    │  │  Config        │   │ │
│  │  │  (SQLite)      │  │  Store       │  │  (JSON)        │   │ │
│  │  └────────────────┘  └──────────────┘  └────────────────┘   │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    Ollama Runtime                             │ │
│  │              gemma4:e4b-it-qat (QAT 4-bit)                   │ │
│  │              macOS: Metal GPU · Windows: CUDA/CPU            │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 进程模型

```
┌─────────────────────┐
│  Platform Shell     │  ← macOS: Swift 菜单栏进程
│  (原生进程)         │  ← Windows: Python + pystray 进程
└────────┬────────────┘
         │ HTTP IPC (localhost:18732)
         ▼
┌─────────────────────┐
│  FastAPI Backend    │  ← 单进程，async
│  (Python)           │  ← 端口 18732 (可配置)
└────────┬────────────┘
         │ Ollama HTTP API (localhost:11434)
         ▼
┌─────────────────────┐
│  Ollama Server      │  ← 独立进程，TeXada 管理生命周期
│  (gemma4:e4b-qat)   │  ← 首次调用自动拉起
└─────────────────────┘
```

---

## 2. 双平台架构

### 2.1 平台抽象层

所有平台差异收束到 `PlatformAdapter` 接口，后端逻辑完全共享：

```python
from abc import ABC, abstractmethod

class PlatformAdapter(ABC):
    """平台抽象层 — 屏蔽 macOS / Windows 差异"""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> None: ...

    @abstractmethod
    def read_clipboard_image(self) -> bytes | None: ...

    @abstractmethod
    def show_notification(self, title: str, body: str) -> None: ...

    @abstractmethod
    def get_hotkey_manager(self) -> "HotkeyManager": ...

    @abstractmethod
    def get_shell_provider(self) -> "ShellProvider": ...


class macOSAdapter(PlatformAdapter):
    """macOS 实现 — pbcopy / NSPasteboard / NSUserNotification"""
    def copy_to_clipboard(self, text: str) -> None:
        subprocess.run(["pbcopy"], input=text, text=True, check=True)

    def read_clipboard_image(self) -> bytes | None:
        # 通过 pngpaste 或 NSPasteboard 读取
        ...


class WindowsAdapter(PlatformAdapter):
    """Windows 实现 — win32clipboard / Pillow / Win10 Toast"""
    def copy_to_clipboard(self, text: str) -> None:
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.SetClipboardText(text)
        win32clipboard.CloseClipboard()
```

### 2.2 平台差异矩阵

| 能力 | macOS | Windows |
|------|-------|---------|
| 菜单栏/系统托盘 | Swift NSStatusItem | pystray (Python) |
| 弹出面板 | NSPopover / WebView | tkinter Toplevel |
| 全局快捷键 | Carbon HotKey API | pynput / keyboard |
| 剪贴板 | pbcopy / NSPasteboard | win32clipboard |
| 截图粘贴 | pngpaste | Pillow ImageGrab |
| 通知 | osascript / UNUserNotification | win10toast / winrt |
| Ollama GPU | Metal (Apple Silicon) | CUDA / CPU |
| 模型加速 | Metal Performance Shaders | cuBLAS / AVX2 |
| 服务管理 | launchd | Windows Service / Task Scheduler |

### 2.3 Shell 实现

**macOS** — 原生 Swift 菜单栏应用，通过 HTTP 与 Python 后端通信：

```
TeXada.app (Swift)
├── AppDelegate.swift      → NSStatusItem 注册菜单栏图标
├── PopoverController.swift → NSPopover 管理 WebView 面板
├── HotkeyManager.swift     → ⌥⌘T 全局快捷键 (Carbon API)
├── IPCClient.swift         → HTTP 请求到 localhost:18732
└── WebView/
    └── panel.html          → 内嵌 WebView 渲染 UI
```

**Windows** — 纯 Python 实现，pystray 系统托盘 + tkinter 面板：

```
texada_shell.py
├── SystemTray              → pystray 图标 + 菜单
├── PopupPanel              → tkinter Toplevel (暗色主题)
├── HotkeyManager           → keyboard 库注册 Win+T
└── IPCClient               → HTTP 请求到 localhost:18732
```

---

## 3. 后端架构

### 3.1 FastAPI 服务

```python
# src/texada/api.py
from fastapi import FastAPI, UploadFile, HTTPException
from pydantic import BaseModel

app = FastAPI(title="TeXada", version="2.0")

# ── 请求/响应模型 ──

class ConvertRequest(BaseModel):
    text: str
    context: str = ""
    intent_override: str | None = None
    render_mode: str = "katex"  # "katex" | "latex"

class LaTeXResponse(BaseModel):
    latex: str                          # 裸 LaTeX 源码
    katex_html: str | None = None       # KaTeX 渲染 HTML (katex 模式)
    latex_highlighted: str | None = None # 语法高亮 HTML (纯 LaTeX 模式)
    copy_text: str                       # ⌘C 复制的文本 (含/不含定界符)
    valid: bool
    source: str                          # "model" | "shorthand" | "template" | "fixed"
    intent: str
    confidence: float
    latency_ms: float
    tokens_used: int = 0

class OCRRequest(BaseModel):
    render_mode: str = "katex"

class ValidateRequest(BaseModel):
    latex: str

class ShorthandRequest(BaseModel):
    key: str
    value: str

# ── 端点 ──

@app.post("/api/convert", response_model=LaTeXResponse)
async def convert_text(req: ConvertRequest): ...

@app.post("/api/ocr", response_model=LaTeXResponse)
async def convert_image(image: UploadFile, render_mode: str = "katex"): ...

@app.post("/api/complete", response_model=LaTeXResponse)
async def complete_latex(req: ConvertRequest): ...

@app.post("/api/validate")
async def validate_latex(req: ValidateRequest): ...

@app.get("/api/shorthands")
async def list_shorthands(q: str = ""): ...

@app.post("/api/shorthands")
async def add_shorthand(req: ShorthandRequest): ...

@app.delete("/api/shorthands/{key}")
async def delete_shorthand(key: str): ...

@app.get("/api/history")
async def list_history(q: str = "", limit: int = 50): ...

@app.get("/api/status")
async def get_status(): ...

@app.post("/api/render-mode")
async def set_render_mode(mode: str): ...
```

### 3.2 服务就绪检测与自动启动

E4B 是端侧模型，不存在"离线"概念。唯一异常是 Ollama 服务未运行：

```python
class OllamaManager:
    """管理 Ollama 生命周期 — 不存在"离线降级"，只有"服务未启动""""

    def __init__(self, config: Config):
        self.config = config
        self.client = ollama.Client(host=config.ollama_host)

    async def ensure_ready(self) -> bool:
        """确保 Ollama 运行且模型已加载"""
        # 1. 检测 Ollama 进程
        if not self._is_ollama_running():
            await self._start_ollama()

        # 2. 检测模型是否已拉取
        models = self.client.list()
        if not any(m.name.startswith("gemma4:e4b") for m in models):
            raise HTTPException(503, "模型未安装，请运行: ollama pull gemma4:e4b-it-qat")

        return True

    def _is_ollama_running(self) -> bool:
        try:
            self.client.ps()
            return True
        except:
            return False

    async def _start_ollama(self) -> None:
        """自动启动 Ollama 服务"""
        import asyncio
        if sys.platform == "darwin":
            proc = await asyncio.create_subprocess_exec("ollama", "serve")
        elif sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec("ollama", "serve")
        # 等待就绪
        for _ in range(30):  # 最多等 30 秒
            await asyncio.sleep(1)
            if self._is_ollama_running():
                return
        raise HTTPException(503, "Ollama 启动超时")
```

**UI 表现**:

| 状态 | 顶栏显示 | 用户感知 |
|------|---------|---------|
| Ollama 运行 + 模型加载 | 🟢 E4B Ready | 正常使用 |
| Ollama 未运行 | 🟡 启动中… | 自动拉起，1-3s 后就绪 |
| 模型未安装 | 🔴 模型未安装 | 提示 `ollama pull` 命令 |
| Ollama 启动超时 | 🔴 启动失败 | 提示手动排查 |

缩写/历史/验证功能**始终可用**，不依赖 Ollama。

---

## 4. 输入管线

### 4.1 Input Router

统一入口，6 个 Tab 对应 5 种路由：

```python
class InputRouter:
    def route(self, tab: Tab, content: str | bytes) -> Route:
        if tab == Tab.OCR:
            return Route.OCR
        if tab == Tab.SHORTHAND:
            return Route.SHORTHAND
        if tab == Tab.COMPLETION:
            return Route.COMPLETION
        # NL Tab — 自动检测
        if isinstance(content, str):
            if self.shorthand_store.has(content.strip()):
                return Route.SHORTHAND  # NL 输入命中缩写
            if self._is_partial_latex(content):
                return Route.COMPLETION  # NL 输入含 LaTeX 片段
            return Route.NL2LATEX
        if isinstance(content, bytes):
            return Route.OCR  # 图片数据
```

### 4.2 Intent Classifier (零模型)

```python
INTENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("integral",    re.compile(r"(积分|∫|integral|integrate|二重积分|三重积分|线积分)", re.I)),
    ("derivative",  re.compile(r"(导数|微分|derivative|diff|d/dx|偏导|梯度|∇)", re.I)),
    ("sum",         re.compile(r"(求和|∑|sum|series|级数)", re.I)),
    ("limit",       re.compile(r"(极限|lim|limit|→|趋近)", re.I)),
    ("matrix",      re.compile(r"(矩阵|matrix|det|行列式|特征值|eigen)", re.I)),
    ("probability", re.compile(r"(概率|P\(|期望|方差|E\[|Var\(|分布|正态|泊松)", re.I)),
    ("set",         re.compile(r"(集合|∈|∪|∩|subset|包含)", re.I)),
    ("logic",       re.compile(r"(∀|∃|⇒|⟹|implies|forall|蕴含|等价)", re.I)),
    ("trig",        re.compile(r"(sin|cos|tan|正弦|余弦|正切)", re.I)),
    ("generic",     re.compile(r".*")),
]

class IntentClassifier:
    def classify(self, text: str) -> tuple[str, float]:
        for intent, pattern in INTENT_PATTERNS:
            if pattern.search(text):
                confidence = 0.9 if intent != "generic" else 0.3
                return intent, confidence
        return "generic", 0.3
```

### 4.3 Symbol Engine (零模型)

```python
class SymbolEngine:
    SYMBOL_MAP: dict[str, str] = {
        # 基础运算
        "加": "+", "减": "-", "乘": r"\times", "除": r"\div",
        # 微积分
        "积分": r"\int", "二重积分": r"\iint", "三重积分": r"\iiint",
        "线积分": r"\oint", "导数": r"\frac{d}{dx}",
        "偏导": r"\frac{\partial}{\partial x}",
        # 集合/逻辑
        "属于": r"\in", "不属于": r"\notin",
        "任意": r"\forall", "存在": r"\exists",
        # 希腊字母
        "阿尔法": r"\alpha", "贝塔": r"\beta",
        # 装饰
        "向量": r"\vec", "帽子": r"\hat", "波浪": r"\tilde",
    }

    def pre_translate(self, text: str) -> str:
        """长匹配优先，将中文术语替换为 LaTeX 符号"""
        result = text
        for cn, latex in sorted(self.SYMBOL_MAP.items(),
                                key=lambda x: -len(x[0])):
            result = result.replace(cn, latex)
        return result
```

---

## 5. 推理层

### 5.1 Gemma 4 E4B 封装

```python
class Gemma4E4B:
    def __init__(self, config: Config):
        self.client = ollama.Client(host=config.ollama_host)
        self.model = config.model_name  # "gemma4:e4b-it-qat"

    async def generate_latex(self,
                             preprocessed: str,
                             intent: str,
                             context: str = "") -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
            {"role": "user", "content": preprocessed},
        ]
        if context:
            messages[-1]["content"] += f"\n\n参考上下文: {context}"

        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={
                "temperature": 0.1,
                "num_predict": 256,
                "top_p": 0.9,
            }
        )
        return self._extract_latex(response.message.content)

    async def complete_latex(self, partial: str) -> str:
        messages = [
            {"role": "system", "content": COMPLETION_PROMPT},
            {"role": "user", "content": partial},
        ]
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={"temperature": 0.05, "num_predict": 128},
        )
        return self._extract_latex(response.message.content)

    async def ocr_latex(self, image: bytes) -> str:
        messages = [{
            "role": "user",
            "content": OCR_SYSTEM_PROMPT,
            "images": [image],
        }]
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={"temperature": 0.05, "num_predict": 256},
        )
        return self._extract_latex(response.message.content)
```

### 5.2 Prompt 系统

**NL→LaTeX System Prompt:**

```
你是一个 LaTeX 公式生成器。严格遵守以下规则：

1. 只输出 LaTeX 数学公式，不要输出任何解释文字
2. 公式必须用 $$...$$ 包裹
3. 不要猜测不确定的内容，用 \placeholder{} 标记
4. 优先使用标准 AMS-LaTeX 命令
5. 如果输入包含已翻译的 LaTeX 符号，直接使用，不要重复转换

输出格式：
$$<你的LaTeX公式>$$
```

**补全 System Prompt:**

```
你是一个 LaTeX 补全器。用户给出不完整的 LaTeX 片段，你补全剩余部分。

规则：
1. 只输出完整的 LaTeX 公式，不要解释
2. 保持用户已输入部分不变，只补全缺失部分
3. 用 $$...$$ 包裹完整公式
```

**OCR System Prompt:**

```
你是一个数学公式 OCR 引擎。分析图片中的数学公式，输出对应的 LaTeX 代码。

规则：
1. 只输出 LaTeX 代码，用 $$...$$ 包裹
2. 识别所有数学符号，包括上下标、分数、积分、求和等
3. 如果无法确定某个符号，用 \placeholder{} 标记
4. 忽略图片中的非数学文字
```

**意图分类 Few-shot 库:**

```python
FEW_SHOT_BY_INTENT = {
    "integral": [
        ("不定积分 sin(x)dx", r"$$\int \sin(x)\,dx = -\cos(x) + C$$"),
        ("f(x)从0到1的定积分", r"$$\int_0^1 f(x)\,dx$$"),
    ],
    "derivative": [
        ("f(x)关于x的一阶导数", r"$$\frac{df}{dx}$$"),
        ("u对v的偏导数", r"$$\frac{\partial u}{\partial v}$$"),
    ],
    "sum": [
        ("从i=1到n的x_i求和", r"$$\sum_{i=1}^{n} x_i$$"),
    ],
    "limit": [
        ("x趋近于0时sin(x)/x的极限", r"$$\lim_{x \to 0} \frac{\sin(x)}{x}$$"),
    ],
    "matrix": [
        ("2x2矩阵A的行列式", r"$$\det(A) = \begin{vmatrix} a & b \\ c & d \end{vmatrix}$$"),
    ],
    "probability": [
        ("X服从正态分布N(μ,σ²)", r"$$X \sim \mathcal{N}(\mu, \sigma^2)$$"),
        ("A给定B的条件概率", r"$$P(A|B) = \frac{P(A \cap B)}{P(B)}$$"),
    ],
    "generic": [
        ("欧拉公式", r"$$e^{i\theta} = \cos\theta + i\sin\theta$$"),
    ],
}
```

---

## 6. 双渲染模式

### 6.1 架构

```
                          LaTeX 源码 (唯一真源)
                                 │
                 ┌───────────────┼───────────────┐
                 │                               │
          ┌──────▼──────┐                 ┌───────▼───────┐
          │  KaTeX      │                 │  LaTeX       │
          │  Renderer   │                 │  Highlighter │
          │             │                 │              │
          │  输入: LaTeX │                 │  输入: LaTeX  │
          │  输出: HTML  │                 │  输出: HTML   │
          │  (视觉公式) │                 │  (结构高亮)  │
          │             │                 │              │
          │  ⌘C:       │                 │  ⌘C:        │
          │  $$...$$   │                 │  裸 LaTeX   │
          └─────────────┘                 └──────────────┘
```

**核心设计**: LaTeX 源码是唯一真源，两种渲染模式只是同一数据的不同视图。切换模式不需要重新推理，只重新渲染。

### 6.2 RenderEngine

```python
class RenderEngine:
    def __init__(self, config: Config):
        self.mode = config.default_render_mode  # "katex" | "latex"
        self.delimiter = config.delimiter         # "$$" | "\[" | "$"

    def render(self, latex: str) -> RenderResult:
        """根据当前模式渲染"""
        return RenderResult(
            latex=latex,
            katex_html=self._render_katex(latex) if self.mode == "katex" else None,
            latex_highlighted=self._highlight_latex(latex) if self.mode == "latex" else None,
            copy_text=self._format_copy(latex),
        )

    def switch_mode(self, mode: str) -> RenderResult:
        """⌘K 切换模式 — 只重新渲染，不重新推理"""
        self.mode = mode
        # 上一次的 latex 源码缓存，直接重新渲染
        return self.render(self._last_latex)

    def _render_katex(self, latex: str) -> str:
        """KaTeX 渲染 → 视觉公式 HTML"""
        result = subprocess.run(
            ["npx", "katex", "-f", "tex", "--output-type", "html"],
            input=latex, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout
        raise RenderError(f"KaTeX render failed: {result.stderr}")

    def _highlight_latex(self, latex: str) -> str:
        """纯 LaTeX 语法高亮 → 结构 HTML"""
        return self.latex_highlighter.highlight(latex)

    def _format_copy(self, latex: str) -> str:
        """根据当前模式格式化复制文本"""
        if self.mode == "katex":
            # KaTeX 模式：带定界符
            return f"{self.delimiter}{latex}{self.delimiter}"
        else:
            # 纯 LaTeX 模式：裸 LaTeX
            return latex
```

### 6.3 LaTeX 语法高亮器

纯 LaTeX 模式下，将 LaTeX 源码按语义角色着色：

```python
class LaTeXHighlighter:
    """将 LaTeX 源码按语义角色标记，生成带颜色的 HTML"""

    # 语义角色 → CSS class → 颜色
    ROLES = {
        "structural": "latex-structural",  # 紫色 — \frac \int \sum \partial
        "operator":   "latex-operator",    # 橙色 — 变量名 x y f
        "frac":       "latex-frac",       # 绿色 — \frac \dfrac \tfrac
        "delimiter":  "latex-delimiter",  # 灰色 — { } _ ^ ( )
    }

    STRUCTURAL_COMMANDS = {
        r"\frac", r"\dfrac", r"\tfrac", r"\sqrt", r"\sum", r"\int",
        r"\iint", r"\iiint", r"\oint", r"\prod", r"\lim", r"\partial",
        r"\nabla", r"\det", r"\binom", r"\hat", r"\vec", r"\tilde",
        r"\overline", r"\underline", r"\overrightarrow", r"\mathcal",
        r"\mathbf", r"\mathrm", r"\mathbb", r"\infty",
    }

    FRAC_COMMANDS = {r"\frac", r"\dfrac", r"\tfrac"}

    def highlight(self, latex: str) -> str:
        """将 LaTeX 转为语法高亮 HTML"""
        tokens = self._tokenize(latex)
        html_parts = []
        for token_type, value in tokens:
            css_class = self.ROLES.get(token_type, "")
            if css_class:
                html_parts.append(f'<span class="{css_class}">{self._esc(value)}</span>')
            else:
                html_parts.append(self._esc(value))
        return "".join(html_parts)

    def _tokenize(self, latex: str) -> list[tuple[str, str]]:
        """词法分析：将 LaTeX 拆分为语义 token"""
        tokens = []
        i = 0
        while i < len(latex):
            # 匹配命令 \xxx
            if latex[i] == '\\':
                j = i + 1
                while j < len(latex) and latex[j].isalpha():
                    j += 1
                cmd = latex[i:j]
                if cmd in self.FRAC_COMMANDS:
                    tokens.append(("frac", cmd))
                elif cmd in self.STRUCTURAL_COMMANDS:
                    tokens.append(("structural", cmd))
                else:
                    tokens.append(("structural", cmd))
                i = j
            # 匹配定界符
            elif latex[i] in '{}_ ^()':
                tokens.append(("delimiter", latex[i]))
                i += 1
            # 匹配变量/运算符
            elif latex[i].isalpha():
                tokens.append(("operator", latex[i]))
                i += 1
            else:
                tokens.append(("", latex[i]))
                i += 1
        return tokens
```

### 6.4 模式切换交互

```
用户按 ⌘K
    │
    ▼
[Shell] → POST /api/render-mode {mode: "katex"|"latex"}
    │
    ▼
[RenderEngine.switch_mode()] → 读取缓存的 LaTeX 源码
    │
    ├─ 切到 katex → _render_katex() → 返回视觉公式 HTML + copy_text=$$...$$
    │
    └─ 切到 latex → _highlight_latex() → 返回结构高亮 HTML + copy_text=裸LaTeX
    │
    ▼
[Shell] → 更新 WebView / tkinter 面板
```

**关键**: 切换模式 **0 模型调用**，延迟 <50ms (KaTeX 渲染) 或 <5ms (语法高亮)。

---

## 7. Validation Layer

### 7.1 校验管线

```
模型输出
    │
    ▼
[1. 花括号配对] ─── ❌ → LaTeX Fixer 自动补全
    │
    ▼
[2. 环境配对]    ─── ❌ → LaTeX Fixer 自动补全 \end{}
    │
    ▼
[3. 命令合法性]  ─── ❌ → LaTeX Fixer 替换已知错误命令
    │
    ▼
[4. KaTeX 解析]  ─── ❌ → 尝试 LaTeX Fixer，仍失败则重新调用模型
    │
    ▼
✅ 通过 → 交给 RenderEngine
```

### 7.2 LaTeX Fixer

```python
class LaTeXFixer:
    def fix(self, latex: str, errors: list[CheckResult]) -> FixResult:
        fixed = latex
        fix_log = []
        for error in errors:
            if error.type == "brace_unbalanced":
                fixed, log = self._fix_braces(fixed)
                fix_log.append(log)
            elif error.type == "env_unbalanced":
                fixed, log = self._fix_env(fixed)
                fix_log.append(log)
            elif error.type == "unknown_command":
                fixed, log = self._fix_command(fixed, error.detail)
                fix_log.append(log)
        return FixResult(latex=fixed, fixed=bool(fix_log), log=fix_log)

    def _fix_braces(self, latex: str) -> tuple[str, str]:
        depth = 0
        for ch in latex:
            if ch == '{': depth += 1
            elif ch == '}': depth -= 1
        if depth > 0:
            latex += '}' * depth
            return latex, f"补全 {depth} 个 }} "
        if depth < 0:
            # 删除多余的 }
            latex = '{' * abs(depth) + latex
            return latex, f"补全 {abs(depth)} 个 {{"
        return latex, ""

    def _fix_env(self, latex: str) -> tuple[str, str]:
        """补全缺失的 \end{...}"""
        begins = re.findall(r'\\begin\{(\w+)\}', latex)
        ends = re.findall(r'\\end\{(\w+)\}', latex)
        missing = []
        for env in begins:
            if begins.count(env) > ends.count(env):
                latex += f'\\end{{{env}}}'
                missing.append(env)
        if missing:
            return latex, f"补全 \\end{{{', '.join(missing)}}}"
        return latex, ""

    # 常见模型错误命令映射
    COMMAND_FIXES = {
        r"\begin{array}": r"\begin{aligned}",  # E4B 常混淆
    }

    def _fix_command(self, latex: str, bad_cmd: str) -> tuple[str, str]:
        fix = self.COMMAND_FIXES.get(bad_cmd)
        if fix:
            latex = latex.replace(bad_cmd, fix)
            return latex, f"替换 {bad_cmd} → {fix}"
        return latex, ""
```

### 7.3 验证 + 修复 完整流程

```
模型输出: "A^{-1 = \frac{1}{\det(A)}"
    │
    ▼
[brace_unbalanced] → depth=1 → 自动补全 "}" → "A^{-1} = \frac{1}{\det(A)}"
    │
    ▼
[env_balance]     → ✅
    │
    ▼
[command_valid]   → ✅
    │
    ▼
[katex_parse]      → ✅
    │
    ▼
✅ 输出修复版，标记 source="fixed"
```

UI 中显示修复提示条：

```
🔧 自动修复: 花括号不匹配 → 已补全 1 个 } （无需重试模型）
```

---

## 8. OCR Pipeline

### 8.1 图像预处理 (零模型)

```python
class ImagePreprocessor:
    def enhance(self, image: bytes) -> bytes:
        img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)

        # 1. 高斯去噪
        img = cv2.GaussianBlur(img, (3, 3), 0)

        # 2. 自适应二值化
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 3. 超分辨率 (2x)
        img = cv2.resize(img, None, fx=2, fy=2,
                         interpolation=cv2.INTER_CUBIC)

        return cv2.imencode('.png', img)[1].tobytes()
```

### 8.2 OCR 流程

```
用户拖入/粘贴图片
    │
    ▼
[Input Router] → type=image → Route.OCR
    │
    ▼
[ImagePreprocessor] → 去噪 + 二值化 + 2x 缩放 (~10ms)
    │
    ▼
[Gemma4E4B.ocr_latex()] → 多模态推理 (~2-4s)
    │
    ▼
[Validation] → 校验 + 自动修复
    │
    ▼
[RenderEngine] → 当前模式渲染
    │
    ▼
[Output] → 复制 / 插入
```

---

## 9. 数据持久化

### 9.1 存储方案

| 数据 | 格式 | 位置 | 说明 |
|------|------|------|------|
| 历史记录 | SQLite | `~/.texada/history.db` | 自动清理 >30 天 |
| 缩写库 | JSON | `~/.texada/shorthands.json` | 内置默认 + 用户自定义 |
| 模板库 | JSON | `~/.texada/templates.json` | 内置默认 + 用户自定义 |
| 配置 | JSON | `~/.texada/config.json` | 所有设置项 |
| KaTeX 缓存 | 内存 | — | 最近 20 条渲染结果 LRU |

### 9.2 SQLite Schema

```sql
CREATE TABLE history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    input_type TEXT NOT NULL,        -- "nl" | "ocr" | "completion" | "shorthand"
    latex      TEXT NOT NULL,
    intent     TEXT NOT NULL,
    source     TEXT NOT NULL,         -- "model" | "shorthand" | "template" | "fixed"
    render_mode TEXT NOT NULL,        -- "katex" | "latex"
    valid      BOOLEAN NOT NULL,
    latency_ms REAL NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    starred    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_history_created ON history(created_at DESC);
CREATE INDEX idx_history_input ON history(input_text);
```

### 9.3 配置结构

```python
class TeXadaConfig(BaseModel):
    # 模型
    ollama_host: str = "http://localhost:11434"
    model_name: str = "gemma4:e4b-it-qat"
    temperature: float = 0.1
    max_tokens: int = 256
    auto_retry: bool = True

    # 渲染
    default_render_mode: str = "katex"    # "katex" | "latex"
    delimiter: str = "$$"                  # "$$" | "\[" | "$"
    katex_enabled: bool = True
    latex_highlight_enabled: bool = True

    # 服务
    api_host: str = "127.0.0.1"
    api_port: int = 18732

    # 快捷键
    hotkey_wake: str = "cmd+alt+t"       # macOS / Windows
    hotkey_switch_mode: str = "cmd+k"

    # 历史
    history_max_days: int = 30
    history_max_items: int = 1000
```

---

## 10. 快捷键系统

| 操作 | macOS | Windows |
|------|-------|---------|
| 唤醒面板 | ⌥⌘T | Win+T |
| 发送/确认 | Enter | Enter |
| 换行 | Shift+Enter | Shift+Enter |
| 关闭面板 | Esc | Esc |
| 切换 Tab | 1-6 | 1-6 |
| **切换渲染模式** | **⌘K** | **Ctrl+K** |
| 复制结果 | ⌘C | Ctrl+C |
| 接受补全 | Tab | Tab |

```python
class HotkeyManager(ABC):
    @abstractmethod
    def register(self, key: str, callback: Callable) -> None: ...
    @abstractmethod
    def unregister(self, key: str) -> None: ...
    @abstractmethod
    def unregister_all(self) -> None: ...

class MacOSHotkeyManager(HotkeyManager):
    """使用 Carbon HotKey API 注册全局快捷键"""
    ...

class WindowsHotkeyManager(HotkeyManager):
    """使用 keyboard 库注册全局快捷键"""
    ...
```

---

## 11. 用户状态机

UI 中 12 个场景对应的后端状态转换：

```
                        ┌─────────┐
          ⌥⌘T ────────▶│  IDLE   │◀──── Esc
                        └────┬────┘
                             │
              ┌──────────┬───┼───┬──────────┐
              │          │   │   │          │
              ▼          ▼   ▼   ▼          ▼
         ┌────────┐ ┌───────┐ ┌──────┐ ┌─────────┐
         │  NL    │ │  OCR  │ │ 补全 │ │  缩写   │
         │ INPUT  │ │ DROP  │ │INPUT │ │ BROWSE  │
         └───┬────┘ └───┬───┘ └──┬───┘ └────┬────┘
             │          │        │          │
             │ Enter    │ 图片   │ Enter    │ Enter
             │          │ loaded │          │
             ▼          ▼        ▼          ▼
         ┌──────────────────────────────────────┐
         │           PROCESSING                  │
         │  ┌─────────────────────────────────┐ │
         │  │ Route → Preprocess → E4B/Store  │ │
         │  │ → Validate → Fix → Render       │ │
         │  └─────────────────────────────────┘ │
         └───────────────────┬──────────────────┘
                             │
                             ▼
                      ┌─────────────┐
                      │   RESULT    │◀──── ⌘K (切换渲染模式)
                      │             │
                      │  KaTeX 视图 │◀──┐
                      │  纯LaTeX视图│──┘  无模型调用，<50ms
                      └──────┬──────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
                ▼            ▼            ▼
           ⌘C 复制      编辑/重新生成   收藏
                │            │            │
                ▼            ▼            ▼
           粘贴到目标    回到INPUT    保存到缩写库
```

---

## 12. 完整数据流

### 12.1 NL→LaTeX (主流程)

```
用户输入: "二重积分 f(x,y) 在区域 D 上"
    │
    ▼
[InputRouter] → type=text, not shorthand → Route.NL2LATEX
    │
    ▼
[IntentClassifier] → match "二重积分" → intent="integral", confidence=0.9
    │
    ▼
[SymbolEngine] → "\\iint f(x,y) 在区域 D 上"
    │               (中文术语已替换，"在区域 D 上" 保留给模型)
    ▼
[Gemma4E4B] → system + few_shot(integral) + preprocessed
    │              temperature=0.1, max_tokens=256
    ▼
模型输出: "$$\\iint_D f(x,y)\\,dx\\,dy$$"
    │
    ▼
[LaTeXValidator] → brace ✅ | env ✅ | command ✅ | katex ✅
    │
    ▼
[RenderEngine] → 根据 current_mode 渲染
    │
    ├─ katex 模式 → KaTeX HTML + copy_text="$$\iint_D f(x,y)\,dx\,dy$$"
    │
    └─ latex 模式 → 语法高亮 HTML + copy_text="\iint_D f(x,y)\,dx\,dy"
    │
    ▼
[OutputAdapter] → clipboard / editor insert / API response
```

### 12.2 缩写展开 (零模型)

```
用户输入: "euler"
    │
    ▼
[InputRouter] → shorthand_store.has("euler") = True → Route.SHORTHAND
    │
    ▼
[ShorthandStore] → lookup("euler") = "e^{i\\pi}+1=0"
    │
    ▼
[RenderEngine] → 渲染
    │
    ▼
[Output] → 直接输出 (<1ms, 0 token)
```

### 12.3 图像 OCR

```
用户粘贴截图 ⌘V
    │
    ▼
[InputRouter] → type=image → Route.OCR
    │
    ▼
[ImagePreprocessor] → 去噪 + 二值化 + 2x (~10ms)
    │
    ▼
[Gemma4E4B.ocr_latex()] → 多模态推理 (~2-4s)
    │
    ▼
[Validation] → 校验 + 自动修复
    │
    ▼
[RenderEngine] → 当前模式渲染
    │
    ▼
[Output] → 剪贴板
```

### 12.4 LaTeX 补全

```
用户输入: "\sum_{i=1}^{"
    │
    ▼
[InputRouter] → is_partial_latex() = True → Route.COMPLETION
    │
    ▼
[Gemma4E4B.complete_latex()] → 补全推理 (~0.3-0.8s)
    │
    ▼
模型输出: "\sum_{i=1}^{n} x_i"
    │
    ▼
[RenderEngine] → 两种模式渲染
    │
    ▼
[Output] → ghost text 显示补全建议，Tab 接受
```

---

## 13. 性能预算

基于 M4 Pro 24GB / Windows RTX 4060 的预期性能：

| 操作 | 模型调用 | 延迟 | Token 消耗 | 说明 |
|------|---------|------|-----------|------|
| Shorthand 展开 | 0 | <1ms | 0 | 纯查表 |
| Intent 分类 | 0 | <1ms | 0 | 正则匹配 |
| Symbol 预翻译 | 0 | <1ms | 0 | 字符串替换 |
| NL→LaTeX (简单) | 1 | ~0.5-1s | ~50-80 | 代数/微积分 |
| NL→LaTeX (复杂) | 1 | ~1-2s | ~80-150 | 多步/嵌套 |
| LaTeX 补全 | 1 | ~0.3-0.8s | ~30-60 | 片段补全 |
| 图像 OCR | 1 | ~2-4s | ~100-200 | 多模态 |
| Validation | 0 | ~10-50ms | 0 | KaTeX 解析 |
| 错误修复 (代码) | 0 | ~5-20ms | 0 | Fixer |
| 错误修复 (模型) | 1 | +1-2s | +50-100 | 重试 |
| **⌘K 切换渲染** | **0** | **<50ms** | **0** | 只重新渲染 |
| KaTeX 渲染 | 0 | ~20-50ms | 0 | npx katex |
| LaTeX 语法高亮 | 0 | ~2-5ms | 0 | 词法分析 |

**关键洞察**: 确定性路径占 ~70% 逻辑但 <5% 延迟。⌘K 切换渲染模式零模型调用。

---

## 14. 项目结构

```
TeXada-the-Math-Agent/
├── src/
│   └── texada/
│       ├── __init__.py
│       ├── __main__.py           # CLI 入口
│       ├── config.py             # TeXadaConfig (Pydantic)
│       ├── platform/            # 平台抽象层
│       │   ├── __init__.py
│       │   ├── base.py          # PlatformAdapter ABC
│       │   ├── macos.py         # macOSAdapter
│       │   └── windows.py       # WindowsAdapter
│       ├── core/                 # 核心业务 (平台无关)
│       │   ├── __init__.py
│       │   ├── router.py         # InputRouter
│       │   ├── intent.py         # IntentClassifier
│       │   ├── symbols.py        # SymbolEngine
│       │   ├── model.py          # Gemma4E4B
│       │   ├── prompts.py        # System prompt + Few-shot
│       │   ├── composer.py       # LaTeXComposer (模板)
│       │   ├── validator.py      # Validation Layer
│       │   ├── fixer.py          # LaTeXFixer
│       │   ├── ocr.py            # OCR Pipeline
│       │   └── ollama_manager.py # Ollama 生命周期
│       ├── render/               # 渲染引擎
│       │   ├── __init__.py
│       │   ├── engine.py         # RenderEngine
│       │   ├── katex.py          # KaTeX Renderer
│       │   └── highlighter.py    # LaTeX Syntax Highlighter
│       ├── store/                # 数据持久化
│       │   ├── __init__.py
│       │   ├── shorthand.py      # ShorthandStore
│       │   ├── template.py       # TemplateStore
│       │   ├── history.py        # HistoryStore (SQLite)
│       │   └── config_store.py   # ConfigStore (JSON)
│       ├── output/               # 输出适配
│       │   ├── __init__.py
│       │   ├── clipboard.py      # ClipboardAdapter
│       │   └── editor.py         # Editor Insert (TSF)
│       ├── api.py                # FastAPI 端点
│       └── shell/                # 平台 Shell
│           ├── __init__.py
│           ├── macos/            # macOS Swift 源码
│           │   └── ...           # (单独编译为 TeXada.app)
│           └── windows.py       # Windows pystray + tkinter
├── data/
│   ├── shorthands.json          # 内置默认缩写
│   └── templates.json           # 内置默认模板
├── tests/
│   ├── test_intent.py
│   ├── test_symbols.py
│   ├── test_validator.py
│   ├── test_fixer.py
│   ├── test_highlighter.py
│   ├── test_render_engine.py
│   └── test_integration.py
├── docs/
│   ├── architecture.md          # 本文档
│   ├── design.md                # 设计文档 (v2 功能定义)
│   └── ui-mockup.html           # UI 模拟
├── pyproject.toml
├── requirements.txt
├── README.md
└── v1-archive/                  # v1 代码归档
```

---

## 15. 技术栈

| 层 | 技术 | macOS | Windows |
|----|------|-------|---------|
| LLM 推理 | Ollama (gemma4:e4b-it-qat) | Metal GPU | CUDA / CPU |
| 后端 | Python 3.12 + FastAPI | ✅ | ✅ |
| KaTeX 渲染 | KaTeX (Node.js subprocess) | ✅ | ✅ |
| LaTeX 高亮 | 自研词法分析器 | ✅ | ✅ |
| LaTeX 校验 | sympy + KaTeX | ✅ | ✅ |
| 图像预处理 | OpenCV + Pillow | ✅ | ✅ |
| 菜单栏 | NSStatusItem (Swift) | ✅ | — |
| 系统托盘 | pystray | — | ✅ |
| 弹出面板 | NSPopover + WebView | ✅ | — |
| 弹出面板 | tkinter (暗色主题) | — | ✅ |
| 全局快捷键 | Carbon HotKey API | ✅ | — |
| 全局快捷键 | keyboard 库 | — | ✅ |
| 剪贴板 | pbcopy / NSPasteboard | ✅ | — |
| 剪贴板 | win32clipboard | — | ✅ |
| 数据持久化 | SQLite + JSON | ✅ | ✅ |
| CLI | Typer | ✅ | ✅ |
| 配置 | Pydantic Settings | ✅ | ✅ |
| IPC | HTTP (localhost:18732) | ✅ | ✅ |

---

## 16. 里程碑

### M0: 环境搭建 (Day 1)
- [ ] 安装 Ollama，拉取 gemma4:e4b-it-qat
- [ ] 验证模型可运行
- [ ] 项目骨架，目录结构

### M1: 核心管线 — 零模型 (Day 2-3)
- [ ] PlatformAdapter 接口 + macOS 实现
- [ ] IntentClassifier
- [ ] SymbolEngine
- [ ] ShorthandStore
- [ ] LaTeXValidator
- [ ] LaTeXFixer
- [ ] 单元测试 (全部零模型)

### M2: 推理集成 (Day 4-5)
- [ ] Gemma4E4B 封装
- [ ] OllamaManager (就绪检测 + 自动启动)
- [ ] Prompt 系统 (system + few-shot)
- [ ] NL→LaTeX 端到端
- [ ] LaTeX 补全
- [ ] OCR Pipeline

### M3: 双渲染模式 (Day 6-7)
- [ ] RenderEngine
- [ ] KaTeX Renderer
- [ ] LaTeX Syntax Highlighter
- [ ] ⌘K 模式切换
- [ ] 双模式复制格式

### M4: Shell + 输出 (Day 8-10)
- [ ] macOS 菜单栏 + NSPopover (或 tkinter 替代)
- [ ] Windows pystray + tkinter 面板
- [ ] 剪贴板输出
- [ ] 历史记录 (SQLite)
- [ ] 设置面板
- [ ] 全局快捷键

### M5: 打磨 (Day 11-14)
- [ ] WindowsAdapter 实现
- [ ] 端到端测试 (双平台)
- [ ] 性能基准
- [ ] 文档完善
- [ ] v0.2.0 tag
