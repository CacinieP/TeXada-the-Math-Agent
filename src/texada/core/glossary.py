"""Named-theorem glossary — term name → standard LaTeX, zero model calls.

Why this exists: a 1B model cannot reliably *recall* textbook formulas. In the
real-world corpus (``eval/real_world_set.yaml``, ``named-formula``) it scored
5/20, answering a different theorem, echoing ``\\text{泰勒公式}``, or giving a
definition instead of the formula (issue #87). Those answers are fixed, public
and enumerable, so the product should look them up like it already does for
matrix presets (``core/matrices.py``) and deterministic completion candidates
(``core/candidates.py``).

Scope guard rails:

* only an input that *is* the name matches — after normalisation the text must
  equal an alias exactly, so ``格林公式和斯托克斯公式的区别`` or ``泰勒展开式``
  fall through to the model;
* every entry is validated as KaTeX before it is served, and the resolver
  never rewrites a formula the user described with parameters;
* the table is curated, not scraped: each entry carries the source that the
  formula was transcribed from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PARENS = re.compile(r"[（(][^）)]*[）)]")
_PUNCT = re.compile(r"[\s，。；、,.;:：!！?？\"'“”‘’]+")
_LEAD = re.compile(r"^(?:请|帮我|帮忙|麻烦|我要|我想要|输入|排版|转写|写个|写出|给我)+")
_NAME_SUFFIX = re.compile(r"(?:的)?(?:公式|定理|法则|准则|规则|定义式|表达式|通解公式)$")
_TRAILING_KEYS = re.compile(r"(?:的|是|吧|呢|吗)+$")


@dataclass(frozen=True)
class GlossaryEntry:
    """One curated name → LaTeX mapping."""

    id: str
    names: tuple[str, ...]
    latex: str
    intent: str = "generic"
    note: str = ""
    source: str = ""


# Curated from the local study notes that ship the corpus:
#   ~/Documents/kaoyan-math-301/06-附录/公式手册.md
#   ~/Documents/kaoyan-zhenti-jieda/math1/2025
# Only standard, unambiguous forms are listed; parameterised statements
# ("格林公式，其中 L 是逆时针闭曲线") stay with the model.
ENTRIES: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        id="green",
        names=("格林", "green"),
        latex=(
            r"\oint_L P\,dx+Q\,dy=\iint_D"
            r"\left(\frac{\partial Q}{\partial x}-\frac{\partial P}{\partial y}\right)dx\,dy"
        ),
        intent="integral",
        note="右边是 Q_x-P_y，不是 P_y-Q_x",
        source="公式手册.md §六",
    ),
    GlossaryEntry(
        id="gauss",
        names=("高斯", "gauss", "高斯-奥斯特洛格拉德斯基", "高奥"),
        latex=(
            r"\iiint_\Omega\left(\frac{\partial P}{\partial x}+\frac{\partial Q}{\partial y}"
            r"+\frac{\partial R}{\partial z}\right)dV"
            r"=\oiint_\Sigma P\,dy\,dz+Q\,dz\,dx+R\,dx\,dy"
        ),
        intent="integral",
        note="散度形式与通量形式等价",
        source="公式手册.md §六",
    ),
    GlossaryEntry(
        id="stokes",
        names=("斯托克斯", "stokes", "斯托克斯公式"),
        latex=(
            r"\oint_\Gamma P\,dx+Q\,dy+R\,dz=\iint_\Sigma"
            r"\left(\frac{\partial R}{\partial y}-\frac{\partial Q}{\partial z}\right)dy\,dz"
            r"+\left(\frac{\partial P}{\partial z}-\frac{\partial R}{\partial x}\right)dz\,dx"
            r"+\left(\frac{\partial Q}{\partial x}-\frac{\partial P}{\partial y}\right)dx\,dy"
        ),
        intent="integral",
        source="公式手册.md §六",
    ),
    GlossaryEntry(
        id="bayes",
        names=("贝叶斯", "bayes", "贝叶斯定理"),
        latex=r"P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}",
        intent="probability",
        source="公式手册.md §十",
    ),
    GlossaryEntry(
        id="total-probability",
        names=("全概率", "全概率公式"),
        latex=r"P(B)=\sum_{i=1}^{n}P(A_i)P(B\mid A_i)",
        intent="probability",
        note="先按原因 A_i 分类，再求和",
        source="公式手册.md §十",
    ),
    GlossaryEntry(
        id="wallis",
        names=("华里士", "华里士公式", "wallis", "点火公式"),
        latex=(
            r"\int_0^{\frac{\pi}{2}}\sin^n x\,dx="
            r"\begin{cases}\frac{(n-1)!!}{n!!}\cdot\frac{\pi}{2},&n\text{ 偶}\\"
            r"\frac{(n-1)!!}{n!!},&n\text{ 奇}\end{cases}"
        ),
        intent="integral",
        source="公式手册.md §四",
    ),
    GlossaryEntry(
        id="gram-schmidt",
        names=("施密特正交化", "施密特", "gram-schmidt", "gram schmidt"),
        latex=(
            r"\beta_k=\alpha_k-\sum_{i<k}"
            r"\frac{(\alpha_k,\beta_i)}{(\beta_i,\beta_i)}\beta_i"
        ),
        intent="matrix",
        source="公式手册.md §九",
    ),
    GlossaryEntry(
        id="lagrange-mvt",
        names=("拉格朗日中值", "拉格朗日中值定理", "lagrange mean value"),
        latex=r"f(b)-f(a)=f'(\xi)(b-a)",
        intent="derivative",
        note="ξ 记作 c 也常见",
        source="公式手册.md §三",
    ),
    GlossaryEntry(
        id="rolle",
        names=("罗尔", "rolle", "罗尔中值定理"),
        latex=r"f(a)=f(b)\Rightarrow f'(\xi)=0",
        intent="derivative",
        source="公式手册.md §三",
    ),
    GlossaryEntry(
        id="cauchy-mvt",
        names=("柯西中值", "柯西中值定理", "cauchy mean value"),
        latex=r"\frac{f(b)-f(a)}{g(b)-g(a)}=\frac{f'(\xi)}{g'(\xi)}",
        intent="derivative",
        source="公式手册.md §三",
    ),
    GlossaryEntry(
        id="taylor",
        names=("泰勒", "taylor", "泰勒展开", "泰勒公式"),
        latex=(
            r"f(x)=\sum_{k=0}^{n}\frac{f^{(k)}(x_0)}{k!}(x-x_0)^k"
            r"+o\left((x-x_0)^n\right)"
        ),
        intent="generic",
        note="带皮亚诺余项的展开",
        source="公式手册.md §三",
    ),
    GlossaryEntry(
        id="lhopital",
        names=("洛必达", "l'hopital", "lhopital", "洛必达法则"),
        latex=(
            r"\lim_{x\to a}\frac{f(x)}{g(x)}"
            r"=\lim_{x\to a}\frac{f'(x)}{g'(x)}"
        ),
        intent="limit",
        source="公式手册.md；kaoyan-zhenti-jieda/math1/2025 第3题",
    ),
    GlossaryEntry(
        id="first-order-linear-ode",
        names=(
            "一阶线性微分方程通解",
            "一阶线性方程通解",
            "一阶线性微分方程",
            "一阶线性方程",
        ),
        latex=r"y=e^{-\int P(x)\,dx}\left(\int Q(x)e^{\int P(x)\,dx}dx+C\right)",
        intent="generic",
        note="对应方程 y'+P(x)y=Q(x)",
        source="公式手册.md §八",
    ),
    GlossaryEntry(
        id="second-order-homogeneous-ode",
        names=(
            "二阶常系数齐次线性微分方程通解",
            "二阶常系数齐次线性方程通解",
            "二阶常系数齐次微分方程通解",
        ),
        latex=r"y=C_1e^{r_1x}+C_2e^{r_2x}",
        intent="generic",
        note="两个相异实根的情形",
        source="公式手册.md §八",
    ),
    GlossaryEntry(
        id="clt",
        names=("中心极限", "中心极限定理", "clt", "central limit"),
        latex=(
            r"\frac{\sum_{i=1}^{n}X_i-n\mu}{\sqrt{n}\sigma}"
            r"\xrightarrow{d}N(0,1)"
        ),
        intent="probability",
        source="公式手册.md §十",
    ),
    GlossaryEntry(
        id="sample-variance",
        names=("样本方差", "样本方差的定义式"),
        latex=r"S^2=\frac{1}{n-1}\sum_{i=1}^{n}(X_i-\bar X)^2",
        intent="probability",
        note="分母 n-1 是无偏的来源",
        source="公式手册.md §十；04-概率/README.md",
    ),
    GlossaryEntry(
        id="euler",
        names=("欧拉公式", "欧拉", "euler", "euler's formula"),
        latex=r"e^{i\theta}=\cos\theta+i\sin\theta",
        intent="generic",
        note=r"特例 e^{i\pi}+1=0",
        source="~/.texada/history.db 2026-09-02 真实调用",
    ),
    GlossaryEntry(
        id="squeeze",
        names=("夹逼", "夹逼准则", "夹逼定理", "squeeze"),
        latex=r"g(x)\le f(x)\le h(x),\ \lim g=\lim h=A\Rightarrow\lim f=A",
        intent="limit",
        source="02-高数/01-极限与连续.md §3.1",
    ),
    GlossaryEntry(
        id="path-independence",
        names=(
            "曲线积分与路径无关的条件",
            "曲线积分与路径无关",
            "路径无关的条件",
        ),
        latex=(
            r"P_y=Q_x\quad\left("
            r"\frac{\partial P}{\partial y}=\frac{\partial Q}{\partial x}\right)"
        ),
        intent="integral",
        note="单连通区域内的充要条件",
        source="公式手册.md §六",
    ),
    GlossaryEntry(
        id="binomial-moments",
        names=("二项分布", "二项分布的期望和方差"),
        latex=r"E(X)=np,\quad D(X)=np(1-p)",
        intent="probability",
        source="公式手册.md §十 七大分布表",
    ),
    GlossaryEntry(
        id="integration-by-parts",
        names=("分部积分", "分部积分公式", "integration by parts"),
        latex=r"\int u\,dv=uv-\int v\,du",
        intent="integral",
        source="公式手册.md §四",
    ),
    GlossaryEntry(
        id="newton-leibniz",
        names=("牛顿-莱布尼茨", "牛顿莱布尼茨公式", "微积分基本定理"),
        latex=r"\int_a^b f(x)\,dx=F(b)-F(a)",
        intent="integral",
        note="F 是 f 的一个原函数",
        source="公式手册.md §四",
    ),
    GlossaryEntry(
        id="cauchy-schwarz",
        names=("柯西不等式", "柯西-施瓦茨", "cauchy-schwarz"),
        latex=r"\left(\sum_{i=1}^{n}a_ib_i\right)^2\le\sum_{i=1}^{n}a_i^2\sum_{i=1}^{n}b_i^2",
        intent="generic",
        source="03-线代/README.md",
    ),
    GlossaryEntry(
        id="rank-inequality",
        names=("矩阵乘积的秩不等式", "矩阵乘积的秩", "秩不等式"),
        latex=r"r(AB)\le\min\{r(A),r(B)\}",
        intent="matrix",
        source="公式手册.md §九",
    ),
)


def normalise(text: str) -> str:
    """Reduce an input to the bare name it might be."""
    value = (text or "").strip()
    value = _PARENS.sub("", value)
    value = _PUNCT.sub("", value)
    value = _LEAD.sub("", value)
    value = _NAME_SUFFIX.sub("", value)
    value = _TRAILING_KEYS.sub("", value)
    return value.lower() if not _CJK.search(value) else value


_ALIASES: dict[str, GlossaryEntry] = {}
for _entry in ENTRIES:
    for _name in _entry.names:
        _key = normalise(_name)
        if _key:
            _ALIASES.setdefault(_key, _entry)


def lookup(text: str) -> GlossaryEntry | None:
    """Return the glossary entry when the input *is* a theorem name."""
    key = normalise(text)
    if not key or len(key) < 2:
        return None
    entry = _ALIASES.get(key)
    if entry is None:
        # "格林公式" → normalise drops the suffix, so also try the raw alias.
        entry = _ALIASES.get(normalise(key))
    return entry
