"""Symbol Engine — deterministic Chinese→LaTeX pre-translation, zero model."""
from __future__ import annotations

# Long match first — sorted by descending key length
SYMBOL_MAP: dict[str, str] = {
    # 基础运算
    "点乘": r"\cdot",
    "叉乘": r"\times",
    "正负": r"\pm",
    "负正": r"\mp",
    "乘": r"\times",
    "除": r"\div",
    "加": "+",
    "减": "-",
    # 关系
    "大于等于": r"\geq",
    "小于等于": r"\leq",
    "不等于": r"\neq",
    "远大于": r"\gg",
    "远小于": r"\ll",
    "约等于": r"\approx",
    "正比于": r"\propto",
    "相似": r"\sim",
    "等于": "=",
    # 集合
    "真子集": r"\subsetneq",
    "不属于": r"\notin",
    "子集": r"\subset",
    "并集": r"\cup",
    "交集": r"\cap",
    "空集": r"\emptyset",
    "全集": r"\Omega",
    "任意": r"\forall",
    "存在": r"\exists",
    "属于": r"\in",
    "补集": r"^c",
    # 微积分
    "三重积分": r"\iiint",
    "二重积分": r"\iint",
    "线积分": r"\oint",
    "偏导": r"\frac{\partial}{\partial x}",
    "梯度": r"\nabla",
    "积分": r"\int",
    "无穷": r"\infty",
    "正无穷": r"+\infty",
    "负无穷": r"-\infty",
    "极限": r"\lim",
    "趋向": r"\to",
    "求和": r"\sum",
    "连乘": r"\prod",
    "导数": r"\frac{d}{dx}",
    "二阶导": "''",
    # 线性代数
    "行列式": r"\det",
    "转置": r"^{\top}",
    "逆": r"^{-1}",
    "范数": r"\|\cdot\|",
    "内积": r"\langle \cdot, \cdot \rangle",
    "张量积": r"\otimes",
    "直和": r"\oplus",
    "矩阵": r"\begin{pmatrix}",
    # 概率统计
    "期望": r"\mathbb{E}",
    "方差": r"\mathrm{Var}",
    "协方差": r"\mathrm{Cov}",
    "概率": r"\mathbb{P}",
    "独立同分布": r"\stackrel{\text{iid}}{\sim}",
    # 箭头
    "双向箭头": r"\leftrightarrow",
    "右箭头": r"\rightarrow",
    "左箭头": r"\leftarrow",
    "推出": r"\Rightarrow",
    "等价于": r"\Leftrightarrow",
    "映射到": r"\mapsto",
    # 装饰
    "向量箭头": r"\vec",
    "宽帽子": r"\widehat",
    "宽波浪": r"\widetilde",
    "上双点": r"\ddot",
    "上划线": r"\overline",
    "下划线": r"\underline",
    "上点": r"\dot",
    "帽子": r"\hat",
    "波浪": r"\tilde",
    "向量": r"\vec",
    "横线": r"\bar",
    # 括号
    "右大括号": r"\right\}",
    "左大括号": r"\left\{",
    "右中括号": r"\right]",
    "左中括号": r"\left[",
    "右小括号": r"\right)",
    "左小括号": r"\left(",
    "右尖括号": r"\rangle",
    "尖括号": r"\langle",
    "绝对值": r"|",
    "范数符号": r"\|",
    # 希腊字母
    "阿尔法": r"\alpha",
    "贝塔": r"\beta",
    "伽马": r"\gamma",
    "西格玛": r"\sigma",
    # 常用函数
    "反正切": r"\arctan",
    "反正弦": r"\arcsin",
    "反余弦": r"\arccos",
    "argmin": r"\arg\min",
    "argmax": r"\arg\max",
    "limsup": r"\limsup",
    "liminf": r"\liminf",
    "sin": r"\sin",
    "cos": r"\cos",
    "tan": r"\tan",
    "log": r"\log",
    "ln": r"\ln",
    "exp": r"\exp",
    "max": r"\max",
    "min": r"\min",
    "sup": r"\sup",
    "inf": r"\inf",
    # 特殊
    "对角省略": r"\ddots",
    "竖省略": r"\vdots",
    "省略号": r"\cdots",
    "因为": r"\because",
    "所以": r"\therefore",
    "证毕": r"\blacksquare",
    "分段": r"\begin{cases}",
    "拉普拉斯": r"\Delta",
}


class SymbolEngine:
    """Deterministic pre-translation: Chinese math terms → LaTeX symbols."""

    def pre_translate(self, text: str) -> str:
        """Replace Chinese terms with LaTeX, preserving unknown parts for the model."""
        result = text
        # Sort by descending key length so "三重积分" matches before "积分"
        for cn, latex in sorted(SYMBOL_MAP.items(), key=lambda x: -len(x[0])):
            result = result.replace(cn, latex)
        return result