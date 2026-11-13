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
| G-010 | `rw-045` `\begin{case}fx` | real-world / repair | **fixed** | 已修（PR #81 / issue #77）：`katex_parse` 的 `No such environment: X` 走唯一前缀映射（`case`→`cases`），配合最多 3 轮修复链，最终得到 `\begin{cases}fx\end{cases}` 并通过校验。 |
| G-011 | `rw-044` `\fr`、`rw-052` `\bet` | real-world / repair | **fixed** | 已修（PR #81 / issue #77）：`Unknown control sequence` 走 `TRUNCATED_COMMANDS` 白名单（`\fr`→`\frac`、`\bet`→`\beta` 等），只替换完整命令边界，不误伤 `\frac`。 |
| G-012 | `rw-036`…`rw-041`（只转写不解答） | real-world / no-solving | **fixed (双保险)** | 两条路都补上了（PR #81 / issue #78）：输入侧 `core/scope.py` 增补口语求值说法（`等于几`、`是多少`、`加到…的和`），输出侧新增 `core/evaluation_guard.py`，检出"等号右边是用户没写过的常数"时带 `transcribe_only` 约束重试一次，仍重复求值则记入 `fix_log`。该类目的 `reject_ok` 允许"被 scope 拒绝"也算通过。 |
