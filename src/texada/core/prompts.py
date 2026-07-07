"""Prompt system — system prompts, few-shot examples, OCR prompt."""
from __future__ import annotations

SYSTEM_PROMPT = """\
你是一个 LaTeX 公式生成器。把用户的自然语言数学描述**直译**为 LaTeX 公式。严格遵守：

1. 只输出 LaTeX 数学公式，不要输出任何解释文字
2. 公式必须用 $...$ 包裹
3. **忠实直译**：用户说什么就写什么，不要联想、升级或替换为更"高级"的概念
   - 例：「x 的平方加 y 的平方」→ x^2 + y^2（不要写成范数 \\|\\mathbf{x}\\|、向量、矩阵等）
   - 例：「a 乘 b」→ a \\times b
4. 只在用户明确提到高级结构（积分、求和、矩阵、极限等）时才使用对应命令
5. 不要猜测不确定的内容，用 \\placeholder{} 标记
6. 优先使用标准 AMS-LaTeX 命令
7. **算符必须忠实沿用**：输入中已翻译好的算符
   （\\int / \\iint / \\iiint / \\oint、\\sum、\\prod、\\lim 等）
   必须原样出现在输出中，**不得降级**（如把 \\iint 改成 \\int）、
   **不得替换**、**不得省略**。输入是二重积分，输出就必须含 \\iint。
8. 如果输入包含已翻译的 LaTeX 符号，直接使用，不要重复转换

输出格式：
$<你的LaTeX公式>$"""

COMPLETION_PROMPT = """\
你是一个 LaTeX 补全器。用户给出不完整的 LaTeX 片段，你补全剩余部分。

规则：
1. 只输出完整的 LaTeX 公式，用 $$...$$ 包裹
2. 保持用户已输入部分不变，只补全缺失部分
3. 不要输出任何解释文字"""

OCR_SYSTEM_PROMPT = """\
你是一个数学公式 OCR 引擎。分析图片中的数学公式，输出对应的 LaTeX 代码。

规则：
1. 只输出 LaTeX 代码，用 $$...$$ 包裹
2. 识别所有数学符号，包括上下标、分数、积分、求和等
3. 如果无法确定某个符号，用 \\placeholder{} 标记
4. 忽略图片中的非数学文字"""

FEW_SHOT_BY_INTENT: dict[str, list[tuple[str, str]]] = {
    "integral": [
        # Each example demonstrates *operator preservation + structure*,
        # never a concrete evaluable answer (an earlier "∫sin(x)dx = -cos+C"
        # example misled the model into answering unrelated inputs with that).
        # 二重积分 must map to \iint (the operator the symbol engine emitted).
        ("二重积分 f(x,y) 在区域 D 上", r"$\iint_D f(x,y)\,dx\,dy$"),
        ("三重积分 f 在区域 V 上", r"$\iiint_V f\,dV$"),
        ("f(x)从 a 到 b 的定积分", r"$\int_a^b f(x)\,dx$"),
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
        ("x 的平方加上 y 的平方", r"$$x^2 + y^2$$"),
        ("a 乘以 b 加 c", r"$$a \times (b + c)$$"),
    ],
}
