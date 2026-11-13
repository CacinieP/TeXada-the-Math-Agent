# Real-world corpus（52 条真实语料测试文案）

用途：逐条复制“测试输入”到 TeXada，检查输出是否包含对应的数学结构、以及**有没有越界解答**。
语料与 `docs/test-prompts-100.md`（100 条基础句式）互补：这里只收那 100 条**没有覆盖**的
真实场景，全部可溯源（最后一列）。机读版本是 `eval/real_world_set.yaml`，两条断言层由
`eval/real_world_lib.py` 的 `judge()` 实现，本表由该 YAML 生成，两者必须一致
（`tests/test_real_world_set.py::test_docs_table_matches_the_fixture`）。

判定口径（每条都要过）：

1. 输出非空，且能被 KaTeX 解析（`\bet`、`\fr` 这类拼错命令直接判失败）；
2. 不是整段 `\text{...}` 或纯文字（模型把公式名复述回来的最常见失败形态）；
3. `\text{}` 之外不出现中文（出现了就是在解释，而不是转写）；
4. 不含该条的 `forbid` 片段（`no-solving` 类靠这条拦住“顺手算出答案”）；
5. 含该条的关键结构（`anchor`，`或` 分隔等价写法，空格/`\left`/`\dfrac` 差异已归一）。

> 产品口径：**TeXada 只转公式，不解答。** `no-solving` 六条就是这条边界的回归测试。


## named-formula — 只给公式名 / 定理名

| ID | 测试输入 | 预期关键结构 | 溯源 |
|---|---|---|---|
| rw-001 | `格林公式` | `\oint_L P\,dx` | Documents/kaoyan-math-301/06-附录/公式手册.md §六 |
| rw-002 | `高斯公式` | `\iiint_\Omega` | 公式手册.md §六 |
| rw-003 | `斯托克斯公式` | `\oint_\Gamma` | 公式手册.md §六 |
| rw-004 | `贝叶斯公式` | `P(A \mid B)` | 公式手册.md §十；~/.texada/history.db 2026-11-13 真实调用 |
| rw-005 | `全概率公式` | `\sum_{i=1}^{n}` | 公式手册.md §十 |
| rw-006 | `华里士公式` | `\int_0^{\frac{\pi}{2}}` | 公式手册.md §四 |
| rw-007 | `施密特正交化` | `\beta_k` | 公式手册.md §九 |
| rw-008 | `拉格朗日中值定理` | `f'(\xi)` | 公式手册.md §三 |
| rw-009 | `罗尔定理` | `f'(\xi)=0` | 公式手册.md §三 |
| rw-010 | `柯西中值定理` | `g'(\xi)` | 公式手册.md §三 |
| rw-011 | `泰勒公式` | `x_0` | 公式手册.md §三 |
| rw-012 | `洛必达法则` | `\lim_{x\to a}` | 公式手册.md；kaoyan-zhenti-jieda/math1/2025 第3题 |
| rw-013 | `一阶线性微分方程通解` | `\int` | 公式手册.md §八 |
| rw-014 | `二阶常系数齐次线性微分方程通解` | `C_1e` | 公式手册.md §八 |
| rw-015 | `中心极限定理` | `N(0,1)` | 公式手册.md §十 |
| rw-016 | `样本方差的定义式（分母是 n-1）` | `n-1` | 公式手册.md §十；04-概率/README.md |
| rw-017 | `欧拉公式` | `e^{i\theta} 或 e^{i\pi}` | ~/.texada/history.db 2026-09-02 真实调用（输入 green 曾误出欧拉公式） |
| rw-018 | `夹逼准则` | `\lim` | 02-高数/01-极限与连续.md §3.1 |
| rw-019 | `曲线积分与路径无关的条件` | `\frac{\partial P}{\partial y} 或 P_y` | 公式手册.md §六 |
| rw-020 | `二项分布的期望和方差` | `np` | 公式手册.md §十 七大分布表 |

## lecture-sentence — 讲义与真题整句

| ID | 测试输入 | 预期关键结构 | 溯源 |
|---|---|---|---|
| rw-021 | `f(x) 等于 0 到 x 上 e 的 t 平方次方乘 sin t 的积分` | `\int_0^x` | kaoyan-zhenti-jieda/math1/2025 第1题 题面 |
| rw-022 | `级数 n 从 1 到无穷，通项是 sin(n的三次方乘π除以 n平方加1)` | `\sum_{n=1}^{\infty}` | kaoyan-zhenti-jieda/math1/2025 第2题 题面 |
| rw-023 | `x 趋于 0 时 (1+x) 的 1/x 次方` | `\lim_{x\to 0}` | 公式手册.md §一 1^∞ 型 |
| rw-024 | `区域 D 上 f(x,y) 的重积分，极坐标下先对 r 再对 theta` | `\iint_D 或 \int_{\theta_1}` | 02-高数/05-重积分.md |
| rw-025 | `曲线 L 上对弧长的第一类曲线积分` | `ds` | 02-高数/06-曲线曲面积分.md |
| rw-026 | `曲面 Sigma 上对面积的曲面积分` | `dS` | 02-高数/06-曲线曲面积分.md |
| rw-027 | `拉格朗日乘数法的辅助函数：f 加上 λ 乘 g` | `\lambda` | 公式手册.md §五 |
| rw-028 | `一阶线性方程 y导 加 P(x)y 等于 Q(x) 的通解` | `\int` | 公式手册.md §八 |

## common-mistake — 易混清单（易错写法）

| ID | 测试输入 | 预期关键结构 | 溯源 |
|---|---|---|---|
| rw-029 | `n阶方阵A，kA的行列式` | `k^n` | 公式手册.md §十一 易混清单 |
| rw-030 | `x分之一的原函数，写成带绝对值的对数` | `\ln\|x\|` | 公式手册.md §十一 易混清单 |
| rw-031 | `极坐标下的面积元` | `r\,dr\,d\theta` | 公式手册.md §十一 易混清单 |
| rw-032 | `X与Y独立时，D(X-Y)等于什么` | `D(X)+D(Y)` | 公式手册.md §十一 易混清单 |
| rw-033 | `矩阵和的秩与各自秩之和的不等式` | `\le` | 公式手册.md §九 秩不等式 |
| rw-034 | `矩阵乘积的秩不等式` | `r(AB) 或 \operatorname{rank}(AB)` | 公式手册.md §九 |
| rw-035 | `格林公式右边用偏导数写出的部分` | `\frac{\partial Q}{\partial x}` | 公式手册.md §十一 易混清单 |

## no-solving — 只转写不解答（负向断言）

| ID | 测试输入 | 预期关键结构 | 溯源 |
|---|---|---|---|
| rw-036 | `2+3 等于几` | `2+3` | 产品定位：只转公式不解答 |
| rw-037 | `解方程 x^2-5x+6=0` | `x^2` | 产品定位：只转公式不解答 |
| rw-038 | `1加2加3一直加到100的和` | `\sum` | 产品定位：只转公式不解答 |
| rw-039 | `sin x 从 0 到 π 的定积分等于多少` | `\int` | 产品定位：只转公式不解答 |
| rw-040 | `证明 e 的 iπ 次方加 1 等于 0` | `e^{i\pi}` | 产品定位：只转公式不解答 |
| rw-041 | `3的平方加上4的平方是多少` | `3^2` | 产品定位：只转公式不解答 |

## completion — 半截 LaTeX / 拼错命令

| ID | 测试输入 | 预期关键结构 | 溯源 |
|---|---|---|---|
| rw-042 | `\sum_{i=1}^{` | `\sum_{i=1}` | README 特性示例 |
| rw-043 | `\sqrt{\lg \frac{5x-x^2}{4}` | `\lg\frac{5x-x^2}{4}` | ~/.texada/runs.db 2026-07-31 真实调用（当时 error） |
| rw-044 | `y=(x+2)e^\fr1 x` | `e^\frac1 x 或 \frac{1}{x}` | ~/.texada/runs.db 2026-09-02 真实调用（\fr 拼错） |
| rw-045 | `\begin{case}fx` | `\begin{cases}fx\end{cases}` | ~/.texada/runs.db 2026-07-31 真实调用（当时 error） |
| rw-046 | `\begin{pmatrix}1&2\\` | `\begin{pmatrix}1&2\\3&4\end{pmatrix}` | 公式手册.md §九 |
| rw-047 | `\frac{d}{dx}` | `\frac{d}{dx}` | ~/.texada/runs.db 2026-07-31 真实调用 |
| rw-048 | `\lim_{x \to 0}` | `\lim` | 02-高数/01-极限与连续.md |
| rw-049 | `\int_0^1` | `\int_0^1` | 公式手册.md §四 |
| rw-050 | `\left(\frac{a}{b}` | `\frac{a}{b}` | LaTeX 括号不配对 |
| rw-051 | `\frac{\partial^2 f}{\partial x}` | `\partial` | 02-高数/04-多元微分.md |
| rw-052 | `\alpha + \bet` | `\beta` | 拼写补全（\bet → \beta） |

## 运行

```bash
# 离线：fixture 与判定规则自检（不需要模型）
pytest tests/test_real_world_set.py -q

# 在线基线：对运行中的 TeXada 打真实请求并逐条判定
python eval/run_real_world.py --base-url http://127.0.0.1:18732
```
