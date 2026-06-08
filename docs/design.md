# TeXada — Gemma 4 E4B 端侧数学 Agent 设计文档

> **版本**: v2.0 (全面重设计)
> **日期**: 2026-06-08
> **核心约束**: 必须端侧运行 Gemma 4 E4B，零云端依赖

---

## 0. 设计哲学

**4B 模型不是缩小版的 70B，而是不同物种。** 不能把大模型架构直接缩放到 4B 然后期望同等效果。TeXada 的核心设计原则：

1. **确定性优先，LLM 兜底** — 符号查找、模板填充、语法校验全部由代码完成；LLM 只处理自然语言→形式语言的模糊映射
2. **窄域深做** — 不做通用数学助手，只做 **LaTeX 公式生成与操作** 这一个任务到极致
3. **单轮快出** — E4B 的推理深度有限，避免多轮链式推理；用结构化 prompt + 强 system 约束让模型一次出对
4. **渐进增强** — 基础功能零模型依赖可用，E4B 加持后语义理解升级，未来可替换更强模型

---

## 1. Gemma 4 E4B 能力边界分析

### 1.1 模型规格

| 属性 | 值 |
|------|-----|
| 有效参数 | 4.3B (总 8.6B 含 embedding) |
| 层数 | 42 decoder layers |
| 隐藏维度 | 2560 |
| 注意力头 | 8 query / 2 KV (GQA) |
| 上下文 | 32K tokens |
| 词表 | 262K (Per-Layer Embeddings) |
| 特殊能力 | 原生 function calling, system role, 多模态(图像输入) |

### 1.2 数学能力预估

基于 Gemma 系列历史数据与架构推演：

| 任务类型 | E4B 预期表现 | 设计应对 |
|----------|-------------|---------|
| 简单代数→LaTeX | ✅ 优秀 | 直接生成 |
| 微积分符号→LaTeX | ✅ 良好 | 模板辅助 |
| 中文自然语言→LaTeX | ✅ 良好 | 强 prompt + few-shot |
| 多步推理证明 | ⚠️ 有限 | 拆成单步 + 验证 |
| 复杂图像OCR→LaTeX | ⚠️ 有限 | OpenCV 预处理 + 简化 prompt |
| 创造性数学表达 | ❌ 不可靠 | 纯模板库，不走模型 |

### 1.3 端侧部署方案

**推荐: Ollama + QAT 量化**

```bash
# 安装 Ollama (如未安装)
brew install ollama

# 拉取 QAT 优化模型 (4-bit, ~5.5GB 显存)
ollama pull gemma4:e4b-it-qat

# 验证
ollama list
ollama run gemma4:e4b-it-qat "将二重积分f(x,y)在D上转为LaTeX"
```

| 方案 | 格式 | 显存占用 | 推理速度 (M4 Pro) | 推荐度 |
|------|------|---------|------------------|--------|
| Ollama QAT | GGUF | ~5.5 GB | ~40-60 tok/s | ⭐⭐⭐ |
| Ollama 标准 | GGUF | ~6 GB | ~35-50 tok/s | ⭐⭐ |
| MLX-LM | safetensors | ~5-8 GB | ~50-70 tok/s | ⭐⭐ (需手动配置) |
| LiteRT-LM | .litertlm | ~3.4 GB | ~30-45 tok/s | ⭐ (移动端优先) |

**本机现状**: 已有 `gemma-4-E4B-it.litertlm` (3.4GB, LiteRT 格式，手机用)，需额外拉取 Ollama QAT 版本用于 Mac 端侧推理。

---

## 2. 功能定义

### 2.1 核心功能 (MVP)

| # | 功能 | 输入 | 输出 | E4B 角色 |
|---|------|------|------|---------|
| F1 | 自然语言→LaTeX | 中文/英文数学描述 | LaTeX 公式 | 语义解析 + 生成 |
| F2 | 图像→LaTeX | 手写/印刷公式截图 | LaTeX 公式 | 多模态识别 |
| F3 | LaTeX 补全 | 不完整 LaTeX 片段 | 完整公式 | 上下文推理 |
| F4 | 快捷缩写展开 | 自定义 shorthand | 完整公式 | 查表 (零模型) |
| F5 | LaTeX 语法校验 | LaTeX 字符串 | valid + 修正建议 | 零模型 (sympy+KaTeX) |

### 2.2 增强功能 (v1.1)

| # | 功能 | 说明 |
|---|------|------|
| F6 | 公式变形 | 因式分解、展开、换元等符号操作 |
| F7 | 步骤生成 | 生成解题步骤的 LaTeX 序列 |
| F8 | 批量转换 | 文档中多个公式的批量识别与转换 |
| F9 | 自定义模板 | 用户定义领域模板 (如物理/统计公式族) |

### 2.3 不做的功能 (明确排除)

| 排除项 | 原因 |
|--------|------|
| 通用数学问答 | E4B 推理深度不足，会产出不可靠答案 |
| 代码生成 | 非 TeXada 职责，交给 gemma-agent |
| 证明生成 | 超出 4B 模型可靠范围 |
| 云端 fallback | 违反端侧核心约束 |

---

## 3. 架构设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                    TeXada Agent                          │
│                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  Input    │───▶│  Intent      │───▶│  Pipeline     │  │
│  │  Router   │    │  Classifier  │    │  Dispatcher   │  │
│  └──────────┘    └──────────────┘    └───────┬───────┘  │
│                                              │          │
│                    ┌─────────────────────────┼────┐     │
│                    │                         │    │     │
│              ┌─────▼─────┐  ┌───────────────▼──┐ │     │
│              │  Symbol   │  │   Gemma 4 E4B    │ │     │
│              │  Engine   │  │   (Ollama API)   │ │     │
│              │  (零模型) │  │                  │ │     │
│              └─────┬─────┘  └────────┬────────┘ │     │
│                    │                 │          │     │
│              ┌─────▼─────────────────▼─────┐    │     │
│              │      LaTeX Composer         │    │     │
│              │  (模板填充 + 片段拼接)       │    │     │
│              └─────────────┬──────────────┘    │     │
│                            │                    │     │
│              ┌─────────────▼──────────────┐    │     │
│              │      Validation Layer       │    │     │
│              │  (sympy + KaTeX + 自定义)   │    │     │
│              └─────────────┬──────────────┘    │     │
│                            │                    │     │
│              ┌─────────────▼──────────────┐    │     │
│              │      Output Adapter         │    │     │
│              │  (Clipboard / TSF / API)    │    │     │
│              └────────────────────────────┘    │     │
│                                                  │     │
│  ┌──────────────────────────────────────────┐   │     │
│  │           Shorthand & Template Store      │   │     │
│  │  (JSON 持久化, 用户可编辑)                │   │     │
│  └──────────────────────────────────────────┘   │     │
└─────────────────────────────────────────────────┘
```

### 3.2 核心模块详解

#### 3.2.1 Input Router

统一入口，识别输入类型并路由：

```python
class InputRouter:
    def route(self, input: UserInput) -> Route:
        if input.type == "image":
            return Route.PIPELINE_OCR
        if input.type == "text" and self._is_shorthand(input.content):
            return Route.PIPELINE_SHORTHAND
        if input.type == "text" and self._is_partial_latex(input.content):
            return Route.PIPELINE_COMPLETION
        if input.type == "text":
            return Route.PIPELINE_NL2LATEX
```

#### 3.2.2 Intent Classifier (零模型)

基于规则和正则的意图分类，**不消耗模型 token**：

```python
INTENT_PATTERNS = {
    "integral":     r"(积分|∫|integral|integrate)",
    "derivative":   r"(导数|微分|derivative|diff|d/dx)",
    "sum":          r"(求和|∑|sum|series)",
    "limit":        r"(极限|lim|limit|→)",
    "matrix":       r"(矩阵|matrix|det|行列式)",
    "probability":  r"(概率|P\(|期望|方差|E\[|Var\()",
    "set":          r"(集合|∈|∪|∩|subset)",
    "logic":        r"(∀|∃|⇒|⟹|implies|forall)",
    "generic":      r".*",  # fallback
}
```

#### 3.2.3 Symbol Engine (零模型)

确定性符号处理，**核心价值：减少模型需要生成的内容量**。

```python
class SymbolEngine:
    """将中文数学术语映射到 LaTeX 符号"""

    SYMBOL_MAP = {
        # 基础运算
        "加": "+", "减": "-", "乘": r"\times", "除": r"\div",
        # 微积分
        "积分": r"\int", "二重积分": r"\iint", "三重积分": r"\iiint",
        "线积分": r"\oint", "导数": r"\frac{d}{dx}",
        "偏导": r"\frac{\partial}{\partial x}",
        "梯度": r"\nabla", "拉普拉斯": r"\Delta",
        # 集合
        "属于": r"\in", "不属于": r"\notin",
        "包含于": r"\subseteq", "并集": r"\cup", "交集": r"\cap",
        # 逻辑
        "任意": r"\forall", "存在": r"\exists",
        "蕴含": r"\implies", "等价": r"\iff",
        # 希腊字母
        "阿尔法": r"\alpha", "贝塔": r"\beta",
        "伽马": r"\gamma", "西格玛": r"\sigma",
        # 装饰
        "上划线": r"\overline", "下划线": r"\underline",
        "帽子": r"\hat", "波浪": r"\tilde",
        "向量": r"\vec", "点": r"\dot",
    }

    def pre_translate(self, text: str) -> str:
        """将中文术语替换为 LaTeX 符号，保留未知部分给模型"""
        result = text
        for cn, latex in sorted(self.SYMBOL_MAP.items(),
                                key=lambda x: -len(x[0])):  # 长匹配优先
            result = result.replace(cn, latex)
        return result
```

#### 3.2.4 Gemma 4 E4B 推理层

**核心设计：用 System Prompt 强约束 + Few-shot 示例 + 预处理降复杂度，让 E4B 一次出对。**

```python
SYSTEM_PROMPT = """你是一个 LaTeX 公式生成器。严格遵守以下规则：

1. 只输出 LaTeX 数学公式，不要输出任何解释文字
2. 公式必须用 $...$ 或 $$...$$ 包裹
3. 不要猜测不确定的内容，用 \\placeholder{} 标记
4. 优先使用标准 AMS-LaTeX 命令
5. 如果输入包含已翻译的 LaTeX 符号，直接使用，不要重复转换

输出格式：
$$<你的LaTeX公式>$$"""

FEW_SHOT_EXAMPLES = [
    {
        "user": "二重积分 f(x,y) 在区域 D 上",
        "model": "$$\\iint_D f(x,y)\\,dx\\,dy$$"
    },
    {
        "user": "n维欧氏空间中向量的范数",
        "model": "$$\\|\\mathbf{x}\\| = \\sqrt{\\sum_{i=1}^{n} x_i^2}$$"
    },
    {
        "user": "正态分布 N(μ, σ²) 的概率密度函数",
        "model": "$$f(x) = \\frac{1}{\\sigma\\sqrt{2\\pi}} e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}$$"
    },
    {
        "user": "矩阵 A 的特征值分解",
        "model": "$$A = P\\Lambda P^{-1}$$"
    },
]
```

**Ollama 调用封装：**

```python
class Gemma4E4B:
    def __init__(self, model: str = "gemma4:e4b-it-qat"):
        self.client = ollama.Client()
        self.model = model

    def generate_latex(self, preprocessed_input: str,
                       intent: str,
                       context: str = "") -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
            {"role": "user", "content": preprocessed_input},
        ]
        if context:
            messages[-1]["content"] += f"\n\n参考上下文: {context}"

        response = self.client.chat(
            model=self.model,
            messages=messages,
            options={
                "temperature": 0.1,   # 极低温度，追求确定性
                "num_predict": 256,   # 公式不需要太长
                "top_p": 0.9,
            }
        )
        return self._extract_latex(response.message.content)
```

#### 3.2.5 LaTeX Composer

模板填充 + 片段拼接，处理模型输出中的结构化部分：

```python
class LaTeXComposer:
    TEMPLATES = {
        "integral":       r"\int_{{{lower}}}^{{{upper}}} {expr}\,d{var}",
        "double_integral": r"\iint_{{{domain}}} {expr}\,d{var1}\,d{var2}",
        "series":         r"\sum_{{{lower}}}^{{{upper}}} {expr}",
        "limit":          r"\lim_{{{var}} \to {target}} {expr}",
        "matrix_n":       r"\begin{{bmatrix}} {content} \end{{bmatrix}}",
    }

    def compose(self, template_id: str, **kwargs) -> str:
        """用确定性模板填充，避免模型生成环境控制符"""
        if template_id in self.TEMPLATES:
            return self.TEMPLATES[template_id].format(**kwargs)
        return kwargs.get("raw", "")
```

#### 3.2.6 Validation Layer

多层校验，确保输出 LaTeX 语法正确：

```python
class LaTeXValidator:
    def validate(self, latex: str) -> ValidationResult:
        checks = [
            self._check_brace_balance,     # 花括号配对
            self._check_env_balance,       # 环境配对 (\begin/\end)
            self._check_command_validity,  # 命令合法性
            self._check_sympy_parse,       # sympy 可解析 (可选)
            self._check_katex_render,      # KaTeX 可渲染
        ]
        results = [check(latex) for check in checks]
        return ValidationResult(
            valid=all(r.ok for r in results),
            errors=[r for r in results if not r.ok],
        )

    def _check_katex_render(self, latex: str) -> CheckResult:
        """用 KaTeX 验证渲染 — 最权威的校验"""
        try:
            result = subprocess.run(
                ["npx", "katex", "-f", "tex"],
                input=latex, capture_output=True, text=True, timeout=5
            )
            return CheckResult(ok=result.returncode == 0)
        except Exception as e:
            return CheckResult(ok=False, error=str(e))
```

#### 3.2.7 OCR Pipeline (图像输入)

```python
class OCRPipeline:
    def __init__(self, model: Gemma4E4B):
        self.model = model
        self.preprocessor = ImagePreprocessor()

    def process(self, image: bytes) -> str:
        # Step 1: 图像预处理 (零模型)
        processed = self.preprocessor.enhance(image)

        # Step 2: E4B 多模态推理
        response = self.model.client.chat(
            model=self.model.model,
            messages=[{
                "role": "user",
                "content": OCR_SYSTEM_PROMPT,
                "images": [processed],  # Ollama 原生支持图像
            }],
            options={"temperature": 0.05}
        )
        # Step 3: 验证
        latex = self._extract_latex(response.message.content)
        valid = self.validator.validate(latex)
        if not valid.ok:
            return self._attempt_fix(latex, valid.errors)
        return latex

class ImagePreprocessor:
    """OpenCV 预处理，降低模型识别难度"""
    def enhance(self, image: bytes) -> bytes:
        img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)
        img = cv2.GaussianBlur(img, (3, 3), 0)      # 去噪
        img = cv2.adaptiveThreshold(                   # 自适应二值化
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        img = cv2.resize(img, None, fx=2, fy=2,       # 超分辨率
                         interpolation=cv2.INTER_CUBIC)
        return cv2.imencode('.png', img)[1].tobytes()
```

---

## 4. 数据流

### 4.1 自然语言→LaTeX (主流程)

```
用户输入: "二重积分 f(x,y) 在区域 D 上"
    │
    ▼
[Input Router] → type=text, not shorthand, not partial LaTeX → NL2LATEX
    │
    ▼
[Intent Classifier] → pattern match "二重积分" → intent=integral
    │
    ▼
[Symbol Engine] → "\\iint f(x,y) 在区域 D 上"
    │               (中文术语已替换，保留 "在区域 D 上" 给模型)
    ▼
[Gemma 4 E4B] → system prompt + few-shot(integral) + preprocessed input
    │
    ▼
模型输出: "$$\\iint_D f(x,y)\\,dx\\,dy$$"
    │
    ▼
[LaTeX Composer] → 模板验证 (匹配 double_integral 模板)
    │
    ▼
[Validation] → brace_balance ✅ | env_balance ✅ | katex_render ✅
    │
    ▼
[Output] → 剪贴板复制 + 可选 TSF 输出
```

### 4.2 快捷缩写 (零模型)

```
用户输入: "euler"
    │
    ▼
[Input Router] → is_shorthand("euler") = True → SHORTHAND
    │
    ▼
[Shorthand Store] → lookup("euler") = "e^{i\\pi}+1=0"
    │
    ▼
[Output] → 直接输出，不经过模型
```

### 4.3 图像→LaTeX

```
用户输入: [截图数据]
    │
    ▼
[Input Router] → type=image → OCR
    │
    ▼
[ImagePreprocessor] → 去噪 + 二值化 + 超分辨率
    │
    ▼
[Gemma 4 E4B] → 多模态输入 (image + OCR prompt)
    │
    ▼
[Validation] → 校验 + 自动修复
    │
    ▼
[Output] → LaTeX 公式
```

---

## 5. Prompt 工程策略

### 5.1 核心原则

| 原则 | 做法 | 原因 |
|------|------|------|
| 强 System 约束 | 5 条硬规则 | E4B 容易跑偏，需要严格限制输出格式 |
| 意图相关 few-shot | 按意图分类选 2-3 个示例 | 32K 上下文有限，不浪费在无关示例上 |
| 预处理降复杂度 | Symbol Engine 先翻译 | 减少模型需要理解和生成的 token 数 |
| 极低温度 | temperature=0.1 | 数学公式不需要创造性，追求确定性 |
| 短输出限制 | num_predict=256 | 公式通常 <100 token，限制输出避免废话 |

### 5.2 意图分类 Few-shot 库

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
        ("无穷级数a_n", r"$$\sum_{n=1}^{\infty} a_n$$"),
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

### 5.3 错误恢复策略

当模型输出不合法 LaTeX 时，**不直接重试**（浪费 token），而是走修复管线：

```python
class LaTeXFixer:
    def fix(self, latex: str, errors: list[CheckResult]) -> str:
        for error in errors:
            if error.type == "brace_unbalanced":
                latex = self._fix_braces(latex)
            elif error.type == "env_unbalanced":
                latex = self._fix_env(latex)
            elif error.type == "unknown_command":
                latex = self._fix_command(latex, error.detail)
        return latex

    def _fix_braces(self, latex: str) -> str:
        """自动补全缺失的花括号"""
        depth = 0
        for ch in latex:
            if ch == '{': depth += 1
            elif ch == '}': depth -= 1
        if depth > 0:
            latex += '}' * depth
        return latex
```

---

## 6. Shorthand & Template 系统

### 6.1 默认 Shorthand 库

```json
{
  "euler": "e^{i\\pi}+1=0",
  "euler-g": "e^{i\\theta}=\\cos\\theta+i\\sin\\theta",
  "pyth": "a^2+b^2=c^2",
  "quad": "x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}",
  "binom": "\\binom{n}{k}=\\frac{n!}{k!(n-k)!}",
  "taylor": "f(x)=\\sum_{n=0}^{\\infty}\\frac{f^{(n)}(a)}{n!}(x-a)^n",
  "gauss": "\\int_{-\\infty}^{\\infty}e^{-x^2}dx=\\sqrt{\\pi}",
  "fourier": "\\hat{f}(\\xi)=\\int_{-\\infty}^{\\infty}f(x)e^{-2\\pi ix\\xi}dx",
  "normal": "f(x)=\\frac{1}{\\sigma\\sqrt{2\\pi}}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}",
  "bayes": "P(A|B)=\\frac{P(B|A)P(A)}{P(B)}",
  "stokes": "\\oint_C \\mathbf{F}\\cdot d\\mathbf{r}=\\iint_S(\\nabla\\times\\mathbf{F})\\cdot d\\mathbf{S}",
  "green": "\\oint_C(Pdx+Qdy)=\\iint_D\\left(\\frac{\\partial Q}{\\partial x}-\\frac{\\partial P}{\\partial y}\\right)dA"
}
```

### 6.2 用户自定义

```json
{
  "_meta": {
    "version": 1,
    "user": "default"
  },
  "shorthands": {
    "my-norm": "\\|x\\|_p = \\left(\\sum_{i=1}^{n}|x_i|^p\\right)^{1/p}"
  },
  "templates": {
    "physics-newton": "F = ma = m\\frac{d^2\\mathbf{r}}{dt^2}",
    "physics-schrodinger": "i\\hbar\\frac{\\partial}{\\partial t}\\Psi = \\hat{H}\\Psi"
  }
}
```

---

## 7. API 设计

### 7.1 FastAPI 端点

```python
from fastapi import FastAPI, UploadFile
from pydantic import BaseModel

app = FastAPI(title="TeXada", version="2.0")

class TextRequest(BaseModel):
    text: str
    context: str = ""        # 可选上下文 (如前后文公式)
    intent_override: str = None  # 手动指定意图

class LaTeXResponse(BaseModel):
    latex: str
    valid: bool
    source: str              # "model" | "shorthand" | "template" | "fixed"
    intent: str
    confidence: float        # 0.0-1.0

@app.post("/api/convert", response_model=LaTeXResponse)
async def convert_text(req: TextRequest): ...

@app.post("/api/ocr", response_model=LaTeXResponse)
async def convert_image(image: UploadFile): ...

@app.post("/api/complete", response_model=LaTeXResponse)
async def complete_latex(req: TextRequest): ...

@app.post("/api/validate")
async def validate_latex(latex: str): ...

@app.get("/api/shorthands")
async def list_shorthands(): ...

@app.post("/api/shorthands")
async def add_shorthand(key: str, value: str): ...
```

### 7.2 CLI 接口

```bash
# 交互模式
texada

# 单次转换
texada "二重积分 f(x,y) 在 D 上"

# 从文件
texada --image formula.png

# 补全模式
texada --complete "\sum_{i=1}^{"

# 管道模式
echo "正态分布 N(μ,σ²)" | texada --pipe
```

---

## 8. 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| LLM 推理 | Ollama (gemma4:e4b-it-qat) | QAT 4-bit 量化，~5.5GB 显存 |
| 后端 | Python 3.12 + FastAPI | 异步，轻量 |
| LaTeX 校验 | KaTeX (Node.js) + sympy | 双重校验 |
| 图像预处理 | OpenCV + Pillow | 去噪/二值化/缩放 |
| 输出 | pyperclip (剪贴板) + TSF 协议 | 即用型输出 |
| 数据持久化 | JSON 文件 | shorthand/template 存储 |
| CLI | Typer | 类型安全的 CLI 框架 |
| 配置 | Pydantic Settings | 环境变量 + 配置文件 |

---

## 9. 项目结构

```
TeXada-the-Math-Agent/
├── src/
│   └── texada/
│       ├── __init__.py
│       ├── __main__.py          # CLI 入口
│       ├── config.py            # Pydantic Settings
│       ├── router.py            # Input Router
│       ├── intent.py            # Intent Classifier (零模型)
│       ├── symbols.py           # Symbol Engine (零模型)
│       ├── model.py             # Gemma4E4B 推理封装
│       ├── prompts.py           # System prompt + Few-shot 库
│       ├── composer.py          # LaTeX Composer (模板填充)
│       ├── validator.py         # Validation Layer
│       ├── fixer.py             # LaTeX Fixer (错误恢复)
│       ├── ocr.py               # OCR Pipeline
│       ├── shorthand.py         # Shorthand Store
│       ├── api.py               # FastAPI 端点
│       └── output.py            # Output Adapter
├── data/
│   ├── shorthands.json          # 默认缩写库
│   └── templates.json           # 默认模板库
├── tests/
│   ├── test_symbols.py
│   ├── test_intent.py
│   ├── test_validator.py
│   ├── test_composer.py
│   └── test_integration.py
├── docs/
│   └── design.md                # 本文档
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 10. 性能预算

基于 M4 Pro (24GB) 的预期性能：

| 操作 | 模型调用 | 预期延迟 | Token 消耗 |
|------|---------|---------|-----------|
| Shorthand 展开 | 0 | <1ms | 0 |
| Intent 分类 | 0 | <1ms | 0 |
| Symbol 预翻译 | 0 | <1ms | 0 |
| NL→LaTeX (简单) | 1 | ~0.5-1s | ~50-80 |
| NL→LaTeX (复杂) | 1 | ~1-2s | ~80-150 |
| LaTeX 补全 | 1 | ~0.3-0.8s | ~30-60 |
| 图像 OCR | 1 (多模态) | ~2-4s | ~100-200 |
| Validation | 0 | ~10-50ms | 0 |
| 错误修复 | 0 (代码修复) | ~5-20ms | 0 |
| 重试 (模型修复) | 1 | +1-2s | +50-100 |

**关键洞察**: 确定性路径 (Intent + Symbol + Validation + Fix) 占总逻辑的 ~70%，但耗时 <5%。模型推理只占 ~30% 逻辑但占 ~95% 延迟。这就是"确定性优先"的价值。

---

## 11. 与已有项目的关系

| 项目 | 关系 | 复用 |
|------|------|------|
| `gemma-agent` (Developer/) | 兄弟项目 — 通用 coding agent | 复用 Orchestrator 状态机思路、Ollama 封装模式 |
| `gemma-cace` (Developer/) | 兄弟项目 — coding agent 另一实现 | 参考 tool calling 格式、policy 层 |
| `Gemma` (Developer/) | 调研仓库 — Gemma 4 工具调用报告 | 参考 function calling token 格式 |
| `TeXWizard-VSCode` (GitHub) | 互补 — VS Code 端公式提取 | 未来可做 TeXada ↔ TeXWizard 集成 |
| `MathConnect` (GitHub) | 互补 — 数学教育游戏 | 无直接复用 |

**TeXada 与 gemma-agent 的核心区别**: gemma-agent 是**通用 coding agent**，模型承担规划+决策+执行的核心角色；TeXada 是**窄域 math agent**，模型只做 NL→LaTeX 的模糊映射，确定性代码承担 70% 的工作。

---

## 12. 里程碑

### M0: 环境搭建 (Day 1)
- [ ] 安装 Ollama
- [ ] 拉取 `gemma4:e4b-it-qat`
- [ ] 验证模型可用性
- [ ] 项目骨架 (pyproject.toml, 目录结构)

### M1: 确定性管线 (Day 2-3)
- [ ] Symbol Engine
- [ ] Intent Classifier
- [ ] Shorthand Store
- [ ] LaTeX Validator
- [ ] 单元测试 (零模型，快速验证)

### M2: 模型集成 (Day 4-5)
- [ ] Gemma4E4B 推理封装
- [ ] Prompt 工程 (system + few-shot)
- [ ] NL→LaTeX 端到端
- [ ] LaTeX 补全
- [ ] 错误恢复管线

### M3: 图像 & 输出 (Day 6-7)
- [ ] OCR Pipeline (OpenCV + 多模态)
- [ ] 剪贴板输出
- [ ] FastAPI 服务
- [ ] CLI 入口

### M4: 打磨 & 发布 (Day 8-10)
- [ ] 端到端测试套件
- [ ] 性能基准测试
- [ ] README + 使用文档
- [ ] GitHub push + v0.1.0 tag

---

## 附录 A: Gemma 4 Function Calling 集成 (可选)

如果未来需要让 TeXada 支持 tool calling（如自动调用 sympy 化简、调用 WolframAlpha 验证等），Gemma 4 的原生格式：

```
工具声明: <|tool|>declaration:FUNC_NAME{description:<|"|>...<|"|>,parameters:{...}}<|tool|>
工具调用: <|tool_call|>call:FUNC_NAME{arg:<|"|>value<|"|>}<|tool_call|>
工具响应: <|tool_response|>response:FUNC_NAME{key:value,...}<|tool_response|>
```

**当前决策**: MVP 不使用 function calling。E4B 在窄域 NL→LaTeX 任务中，直接生成比 tool calling 更快更可靠。Function calling 留给 v2.0 的增强功能（公式变形、步骤生成等需要外部工具的场景）。

---

## 附录 B: 本机模型部署检查清单

```bash
# 1. 安装 Ollama
brew install ollama

# 2. 启动服务
ollama serve

# 3. 拉取 QAT 模型
ollama pull gemma4:e4b-it-qat

# 4. 验证
ollama list          # 应看到 gemma4:e4b-it-qat
ollama ps            # 确认可运行

# 5. 快速测试
ollama run gemma4:e4b-it-qat "Convert to LaTeX: double integral of f(x,y) over domain D"

# 6. (可选) 已有 LiteRT 模型用于手机端
ls -lh ~/models/gemma-4-E4B-it.litertlm   # 3.4GB, 已存在
```
