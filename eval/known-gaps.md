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
