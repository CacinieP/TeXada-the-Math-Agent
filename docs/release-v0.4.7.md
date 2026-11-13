# TeXada v0.4.7

发布日期 / Release date 2026-11-13（Asia/Shanghai）。

v0.4.7 修复两类"静默坏结果"：拼错命令与非法环境名此前没有任何自动修复路径，
以及"只转写不解答"只有输入侧门禁、没有输出侧兜底。同时新增 52 条真实语料
评测集与离线判定器，把本轮实测的失败形态固化为回归。

[下载 Release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.7) · [完整 diff](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.6...v0.4.7) · [CHANGELOG](../CHANGELOG.md#047---2026-11-13) · [使用指南](../README.md)

## 本版变化

- 拼错命令与非法环境名可以确定性修复。KaTeX 成为唯一语法权威后，validator
  只产出 `katex_parse` 错误，而 fixer 仍只处理 `brace_unbalanced` /
  `env_unbalanced` / `unknown_command`（后者已不再产生），因此
  `y=(x+2)e^\fr1 x`、`\alpha+\bet`、`\begin{case}fx` 会原样返回坏公式。
  现在 `Undefined control sequence: \X` 走截断命令白名单（只在完整命令边界
  替换，不会把 `\frac` 改成 `\fracrac`），`No such environment: X` 走唯一
  前缀映射（`case`→`cases`；`al` 这种多候选一律不猜）。
- 确定性修复可组合并重新校验。修复轮数上限三轮，`\begin{case}fx` 需要
  「改环境名」+「补 `\end`」两轮完成；三轮后仍非法则保留原答案，仍以
  `valid=false` 暴露给用户，不静默替换。
- "只转写不解答"补上输出侧兜底。输入侧 `scope` 增补口语化求值说法
  （`等于几`、`是几`、`是多少`、`加到 N 的和`），输出侧新增求值守卫：
  等号右边出现用户从未写过的常数即判为求值，带 `transcribe_only` 约束重试
  一次；重试仍求值则保留首个答案并记录 `evaluation-suspected`。
- 新增真实语料评测集 `eval/real_world_set.yaml`（52 条：术语名 20、补全 11、
  讲义整句 8、易混 7、只转写不解答 6），配套 `eval/real_world_lib.py`
  六层判定、`eval/run_real_world.py` 在线基线运行器与 225 条离线断言。
  语料逐条可溯源到本机讲义、真题详解与运行日志。
- 本版实测基线（`minicpm-v4.7-1b`，llama-server，52 条）：通过 31 条。
  `no-solving` 6/6（由输入侧门禁拒绝）、`completion` 10/11、
  `lecture-sentence` 6/8、`common-mistake` 4/7、`named-formula` 5/20。
  该数字只描述这套语料，不构成模型质量的通用结论。

## 边界

- 输出侧求值守卫仅作用于 `/api/convert` 路径；`/api/agent` 的 Agent Runtime
  仍依赖输入侧 `scope` 门禁，作为后续项。
- `named-formula` 的锚点是"最低可判结构"（`\int`、`\lim`），弱锚点登记在
  `eval/known-gaps.md` G-009；`e^{…}` 的 script 绑定差异见 G-013。
- 安装包与模型推理的验收仍按既有规则逐包记录；本轮不改变打包、签名与
  公证流程。