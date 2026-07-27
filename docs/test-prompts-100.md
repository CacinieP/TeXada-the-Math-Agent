# TeXada 100 条人工测试文案

用途：逐条复制“测试输入”到 TeXada 的 NL Agent 页面，检查输出是否包含对应的数学
结构。下表的“预期关键结构”是语义锚点，不要求模型输出与示例逐字符一致；空格、
`\left`/`\right`、`\dfrac`/`\frac` 等等价写法都可接受。

建议每条至少检查：

1. 返回结果非空且显示 `Valid`；
2. 预期关键算符没有丢失或降级；
3. KaTeX 预览与 LaTeX 源码语义一致；
4. Agent 执行轨迹能够展开；
5. 历史记录和运行日志中存在同一个 `run_id`。

## A. 基础代数与方程（001–012）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 001 | x 加上 y | `x+y` |
| 002 | a 减去 b 等于 c | `a-b=c` |
| 003 | 三倍 x 加五等于二十 | `3x+5=20` |
| 004 | x 的平方加上 y 的平方 | `x^2+y^2` |
| 005 | a 加 b 的平方 | `(a+b)^2` |
| 006 | x 与 y 的乘积再加 z | `xy+z` 或 `x\cdot y+z` |
| 007 | x 的绝对值小于等于一 | `\lvert x\rvert\le 1` 或 `|x|\le 1` |
| 008 | 向量 x 的二范数 | `\lVert x\rVert_2` |
| 009 | x 不等于零 | `x\ne 0` |
| 010 | 把 x 平方减一分解成两个因式 | `x^2-1=(x-1)(x+1)` |
| 011 | 一元二次方程 ax 平方加 bx 加 c 等于零 | `ax^2+bx+c=0` |
| 012 | 方程组 x 加 y 等于一，x 减 y 等于三 | `\begin{cases}`、两条方程 |

## B. 分式、根式、幂与上下标（013–025）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 013 | a 除以 b 的分数 | `\frac{a}{b}` |
| 014 | x 加一除以 x 减一 | `\frac{x+1}{x-1}` |
| 015 | 一除以一加一除以 x | 外层和内层两个 `\frac` |
| 016 | x 的平方根 | `\sqrt{x}` |
| 017 | x 加 y 的平方根 | `\sqrt{x+y}` |
| 018 | x 的立方根 | `\sqrt[3]{x}` |
| 019 | x 的 n 次方根 | `\sqrt[n]{x}` |
| 020 | a 除以 b 的平方根 | `\sqrt{\frac{a}{b}}` 或等价结构 |
| 021 | x 的二分之一次方 | `x^{\frac{1}{2}}` |
| 022 | x 的负二次方 | `x^{-2}` |
| 023 | x 的下标 i | `x_i` |
| 024 | a 下标 i 的平方 | `a_i^2` |
| 025 | x 的上标 n 加下标 k | `x_k^n` 或 `x^{n}_{k}` |

## C. 求和、连乘、数列与组合（026–038）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 026 | i 从一到 n 的求和 | `\sum_{i=1}^{n}` |
| 027 | i 从一到 n 的平方和 | `\sum_{i=1}^{n}i^2` |
| 028 | i 从一到 m、j 从一到 n 的双重求和 a 下标 ij | 两个 `\sum`、`a_{ij}` |
| 029 | i 从一到 n 的连乘 x 下标 i | `\prod_{i=1}^{n}x_i` |
| 030 | 从 k 等于零到 n 的有限几何级数 r 的 k 次方 | `\sum_{k=0}^{n}r^k` |
| 031 | 从 k 等于零到无穷的几何级数 r 的 k 次方 | `\sum_{k=0}^{\infty}r^k` |
| 032 | 数列 a 下标 n 等于一除以 n | `a_n=\frac{1}{n}` |
| 033 | 递推式 a 下标 n 加一等于二倍 a 下标 n 加一 | `a_{n+1}=2a_n+1` |
| 034 | 等差数列第 n 项等于首项加 n 减一倍公差 | `a_n=a_1+(n-1)d` |
| 035 | n 选 k 的二项式系数 | `\binom{n}{k}` |
| 036 | n 的阶乘 | `n!` |
| 037 | 从 n 个元素中选 k 个并排列 | `\frac{n!}{(n-k)!}` 或 `P(n,k)` |
| 038 | 从 n 个元素中选 k 个的组合数 | `\frac{n!}{k!(n-k)!}` 或 `\binom{n}{k}` |

## D. 极限、连续与渐近（039–050）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 039 | x 趋近于零时 sin x 除以 x 的极限 | `\lim_{x\to 0}\frac{\sin x}{x}` |
| 040 | x 趋近于无穷时一除以 x 的极限 | `\lim_{x\to\infty}\frac{1}{x}` |
| 041 | x 从右侧趋近于零时 ln x 的极限 | `\lim_{x\to 0^+}\ln x` |
| 042 | n 趋近于无穷时一加一除以 n 的 n 次方 | `\lim_{n\to\infty}(1+\frac1n)^n` |
| 043 | n 趋近于无穷时数列 a 下标 n 等于 L | `\lim_{n\to\infty}a_n=L` |
| 044 | x 趋近于 a 时 f(x) 的极限等于 f(a) | `\lim_{x\to a}f(x)=f(a)` |
| 045 | x 趋近于零时 e 的 x 次方减一除以 x | `\lim_{x\to0}\frac{e^x-1}{x}` |
| 046 | 数列 a 下标 n 的上极限 | `\limsup_{n\to\infty}a_n` |
| 047 | 数列 a 下标 n 的下极限 | `\liminf_{n\to\infty}a_n` |
| 048 | f 在 x 等于 a 处连续的定义 | `\lim_{x\to a}f(x)=f(a)` |
| 049 | 对任意 epsilon 大于零，存在 delta 大于零 | `\forall`、`\epsilon>0`、`\exists`、`\delta>0` |
| 050 | 当 x 趋近无穷时 f(x) 与 g(x) 渐近等价 | `f(x)\sim g(x)`、`x\to\infty` |

## E. 导数、偏导与向量微分（051–062）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 051 | f 对 x 的一阶导数 | `f'(x)` 或 `\frac{df}{dx}` |
| 052 | y 对 x 的二阶导数 | `\frac{d^2y}{dx^2}` |
| 053 | f 对 x 的 n 阶导数 | `\frac{d^nf}{dx^n}` 或 `f^{(n)}(x)` |
| 054 | f 对 x 的偏导数 | `\frac{\partial f}{\partial x}` |
| 055 | f 先对 x 再对 y 的混合偏导 | `\frac{\partial^2 f}{\partial y\partial x}` 或等价次序 |
| 056 | 标量场 f 的梯度 | `\nabla f` |
| 057 | 向量场 F 的散度 | `\nabla\cdot\mathbf{F}` |
| 058 | 向量场 F 的旋度 | `\nabla\times\mathbf{F}` |
| 059 | 函数 F 对变量 x 的雅可比矩阵 | `J_F(x)` 或 `\frac{\partial F}{\partial x}` |
| 060 | 函数 f 的海森矩阵 | `\nabla^2 f` 或 `H_f` |
| 061 | 复合函数 f(g(x)) 的链式法则 | `f'(g(x))g'(x)` |
| 062 | u 除以 v 的求导法则 | `\frac{u'v-uv'}{v^2}` |

## F. 积分与多重积分（063–080）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 063 | x 平方的不定积分 | `\int x^2\,dx` |
| 064 | f(x) 从零到一的定积分 | `\int_0^1 f(x)\,dx` |
| 065 | 二重积分 f(x,y) 在区域 D 上 | `\iint_D` 或 `\iint_{D}` |
| 066 | 三重积分 f(x,y,z) 在区域 Omega 上 | `\iiint_{\Omega}`，不得降级为 `\int` |
| 067 | 沿闭曲线 C 的环路积分 F 点乘 dr | `\oint_C\mathbf F\cdot d\mathbf r` |
| 068 | 曲面 S 上 f 的曲面积分 | `\iint_S f\,dS` |
| 069 | 沿曲线 C 的线积分 f ds | `\int_C f\,ds` |
| 070 | 从负无穷到正无穷的高斯积分 | `\int_{-\infty}^{\infty}e^{-x^2}\,dx` |
| 071 | 一除以 x 平方从一到无穷的反常积分 | `\int_1^\infty\frac{1}{x^2}\,dx` |
| 072 | 分部积分公式 | `\int u\,dv=uv-\int v\,du` |
| 073 | 微积分基本定理：从 a 到 x 的 f(t) 积分对 x 求导 | `\frac{d}{dx}\int_a^x f(t)\,dt=f(x)` |
| 074 | 令 u 等于 g(x) 的换元积分公式 | `u=g(x)`、`du=g'(x)dx` |
| 075 | 极坐标下区域 D 的二重积分 | `\iint_D`、`r\,dr\,d\theta` |
| 076 | 球坐标下区域 Omega 的三重积分 | `\iiint_{\Omega}`、`\rho^2\sin\phi` |
| 077 | 从零到无穷 x 乘 e 的负 x 次方的积分 | `\int_0^\infty xe^{-x}\,dx` |
| 078 | 连续随机变量 X 的期望积分 | `\mathbb E[X]=\int` 或 `E[X]=\int` |
| 079 | 狄拉克 delta 函数从负无穷到正无穷的积分等于一 | `\int_{-\infty}^{\infty}\delta(x)\,dx=1` |
| 080 | 斯托克斯公式，闭曲线 C 的环路积分等于曲面 S 上旋度的积分 | `\oint_C`、`\iint_S`、`\nabla\times` |

## G. 向量、矩阵与线性代数（081–090）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 081 | 三维列向量 x 等于 a、b、c | `\begin{pmatrix}a\\b\\c\end{pmatrix}` |
| 082 | 二乘二矩阵，第一行 a b，第二行 c d | `\begin{pmatrix}a&b\\c&d\end{pmatrix}` |
| 083 | 二乘二矩阵 A 的行列式 | `\det(A)` 或矩阵竖线结构 |
| 084 | 矩阵 A 的逆矩阵 | `A^{-1}` |
| 085 | 矩阵 A 的转置 | `A^{\mathsf T}` 或 `A^T` |
| 086 | 向量 a 与向量 b 的点积 | `\mathbf a\cdot\mathbf b` |
| 087 | 向量 a 与向量 b 的叉积 | `\mathbf a\times\mathbf b` |
| 088 | 特征值方程 A v 等于 lambda v | `A\mathbf v=\lambda\mathbf v` |
| 089 | 矩阵 A 的奇异值分解等于 U Sigma V 转置 | `A=U\Sigma V^{\mathsf T}` |
| 090 | 二乘二矩阵 A 与二乘二矩阵 B 的乘积 | 两个矩阵结构和乘法 |

## H. 概率、统计、集合与逻辑（091–100）

| ID | 测试输入 | 预期关键结构 |
|---:|---|---|
| 091 | 在 B 发生条件下 A 的条件概率 | `P(A\mid B)` |
| 092 | 贝叶斯公式 | `P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}` |
| 093 | 离散随机变量 X 的期望 | `\mathbb E[X]=\sum_x xP(X=x)` 或等价形式 |
| 094 | 随机变量 X 的方差 | `\operatorname{Var}(X)=\mathbb E[(X-\mu)^2]` |
| 095 | 均值 mu、方差 sigma 平方的正态分布密度 | `\frac{1}{\sigma\sqrt{2\pi}}`、指数项 |
| 096 | 集合 A 与集合 B 的并集和交集 | `A\cup B`、`A\cap B` |
| 097 | A 是 B 的子集且 B 是 C 的真子集 | `A\subseteq B`、`B\subset C` |
| 098 | 对任意 x 属于实数，都存在 y 大于 x | `\forall x\in\mathbb R`、`\exists y>x` |
| 099 | 命题 P 蕴含 Q，并且 Q 当且仅当 R | `P\Rightarrow Q`、`Q\Leftrightarrow R` |
| 100 | 分段函数：x 大于等于零时是 x 平方，x 小于零时是负 x | `\begin{cases}`、两个条件分支 |

## 推荐记录格式

人工测试时可复制下面模板：

```text
ID:
输入:
输出 LaTeX:
Valid:
关键结构是否保留:
KaTeX 是否正确:
Agent 步数 / 工具数:
run_id:
备注:
```
