# Known Gaps / 已知限制登记

Triage outcomes from golden set construction and early runs. Verdicts:
**defect** (real bug, filed), **equivalent-spelling** (anchor needs an
equivalent form), **matcher-strict** (MVP matcher limitation),
**scope** (documented product boundary, not a bug).

| ID | Anchor / Case | Layer / Class | Verdict | Action |
|---|---|---|---|---|
| G-001 | `\left(x+1\right)^2` vs `(x+1)^2` | anchor matcher | matcher-strict | KaTeX AST attaches the script to different nodes; token subsequence cannot unify. Upgrade path: structural containment matching (ADR-013 Future). |
| G-002 | Descriptive anchors (`或等价结构` etc., 18 entries) | anchor matcher | scope | `anchor_variants` drops CJK fragments; purely descriptive anchors skip the anchor layer. Manual check retained for those entries. |
| G-003 | Unmatched `\left(` / `\right)` | repair dataset | scope | Measured 2026-09-19: `repair_tex` leaves delimiter-unbalanced input unchanged. Documented boundary; semantic patch (v0.5) is the candidate fix path. |
| G-004 | Stray `$` delimiters | repair dataset | scope | Measured 2026-09-19: not repaired. Same boundary as G-003. |
| G-005 | Empty `{}` argument groups (`\frac{}{2}` etc.) | repair dataset | scope | Measured 2026-09-19: not repaired. Same boundary as G-003. |
| G-006 | `\iiint`→`\int` degradation | repair dataset | scope | Not a repair case: the degraded formula is valid LaTeX. Covered by golden set anchor layer instead (semantic value distinguishes `int`/`iiint`). |
| G-007 | Truncated tool-call JSON from MiniCPM5-2B | live baseline | defect | Measured 2026-09-19: 2/100 entries (051, 053) abort with `invalid tool call arguments for parse_tex: unexpected end of JSON input`. Runtime robustness issue — out of Iteration 1 scope (zero runtime change). Candidate fix: tolerate/retry on malformed tool arguments. |
| G-008 | Structural pass rate 28/95 (29.5%) | live baseline | evidence | First honest NL→LaTeX structural baseline (2026-09-19, live llama-server, MiniCPM5-2B Q4_K_M, 95 machine-checkable anchors). Low but real; baseline for all later iterations, not a defect to fix in Iteration 1. |
| G-009 | `rw-013` / `rw-028`（一阶线性 ODE 通解） | real-world anchor | matcher-strict | anchor 只取 `\int`：`y=e^{-\int P}\left(\int Qe^{\int P}+C\right)` 的括号/分数写法差异过大，逐字符锚会误杀正确解。该两条的语义判定留在人工复核。 |
| G-010 | `rw-045` `\begin{case}fx` | real-world / repair | scope | 语义上应把环境名修正为 `cases`；当前 fixer 只补 `\end{}`，补出 `\end{case}` 仍是非法环境。语料把"补出不存在的环境"记为失败，修复路径候选见 issue（未在本次改动中实现）。 |
| G-011 | `rw-044` `\fr`、`rw-052` `\bet` | real-world / repair | defect | 拼错命令不会被自动修复：validator 改用 KaTeX 后只报 `katex_parse`，而 `LaTeXFixer` 仅处理 `brace_unbalanced` / `env_unbalanced` / `unknown_command`（后者已不再产生）。语料因此将这两条记为失败样例。 |
| G-012 | `rw-036`…`rw-041`（只转写不解答） | real-world / no-solving | evidence | 提示词已禁止求值（`core/prompts.py` 规则 9），但输出层没有守卫；实测 1B 模型会把 `2+3` 算成 `5`、把 `\sum` 算成 `5050`。该类目用 `forbid` 片段把"顺手解答"判为失败，属产品边界回归而非 matcher 问题。 |
