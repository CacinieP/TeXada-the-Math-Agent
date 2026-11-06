# ADR-018 — Parameterized Matrix Candidates

| Field | Value |
|---|---|
| Status | Accepted design, first matrix delivery implemented on an unreleased feature branch |
| Date | 2026-11-06 |
| Layers | Input Layer / Deterministic Tools / Semantic Layer / Evidence Layer |
| Scheduling | Bounded candidate improvements after v0.4.3, with cross-cutting evidence work. Release version awaits scheduling. |
| Baseline | Official v0.4.3 at `6adcba0ab1540f2efb1bf78156783842001bc72c` |

## Problem and current-release evidence

Users need editable matrix presets and faithful generation from descriptions
of matrix structure. A request for a tridiagonal matrix carries constraints
on dimensions, diagonal expressions, index ranges, and zero entries.
Successful compilation supplies syntax evidence. Those request constraints
need their own checks.

On 2026-11-06, 14 requests were replayed through the official v0.4.3 macOS
arm64 package's backend API with its bundled llama-server and a real local
MiniCPM-V-4.7-1B Q4_K_M model. The package was copied into an isolated test
directory, with separate configuration and history. `/api/runtime`, exported
metadata, and all 14 new run fingerprints reported `0.4.3`. Every response
reported `valid=true` and `committed=true`.

The three matrix runs reproduced the following requirement failures.

| Case | Request | New v0.4.3 run ID | Observed result |
|---|---|---|---|
| C10 | 写一个矩阵，主对角线是ai，两条次对角线分别是bi，ci | `1a9965012d7047a893933cb6e4939ee4` | Generic `a_ij` matrix illustration with the specified `b_i`, `c_i`, and tridiagonal pattern missing. |
| C11 | 写一个10阶矩阵，主对角线是ai，两条次对角线分别是bi，ci | `d9f13b145fda403eb72ceecb57c885fc` | Generic matrix illustration with repeated or misplaced indices and the tridiagonal pattern missing. |
| C12 | Same request as C11 | `92ae2ed601264182a390bc69ca49d33d` | Output identical to C11. |

All three stopped at `finish_confirmed`. Their initial candidates already
omitted the requested structure, and the planner finished after compilation.
The traces recorded `mutation_scope.intent_status=NOT_CHECKED`. Because these
outputs contain ellipses, the requirement failures are established by the
missing diagonal expressions and tridiagonal pattern. Ellipsis row counts
alone cannot establish their logical dimensions.

The same replay produced an extra summation factor in C05, an invented
integral upper bound and lost function subscript in C09, and a lost integer
index domain in C14. These cases motivate a separate fidelity issue. The
observed C09 output was
`\sum_{i=1}^n \int_{\omega_i}^{omega_{i+1}} Fi(x)\,dx`.
Its new run ID was `a35e889115054bf3891d3c8ab63c72d9`.

### Reproduction identity and scope

- Official source commit was `6adcba0ab1540f2efb1bf78156783842001bc72c`.
- `TeXada_0.4.3_aarch64.dmg` SHA-256 was
  `aa1a352d5312ad81ca13b13d9a7fb5c77c254e80575f1c905c76cb37edb984f0`,
  matching the published manifest.
- Bundled llama-server build was 11669. Settings were seed 47, temperature
  0.1, context size 8192, `max_tokens=2048`, `agent_max_steps=3`,
  `planner_surface=full`, and `nl_candidate_first=true`, with empty request
  context.
- Model weight SHA-256 was
  `588c6c94c82f756b86dba35c42ed9ba9ec187d65824eb52f039c347df563e63d`.
  Projector SHA-256 was
  `fb9cc047a3cdad5317fd8433a4aeda2d22f00f02ca4bd93b34ad84165b25a900`.
  Both matched the source pins.
- Retained replay export SHA-256 was
  `c23b8862b2b23fd99c0cb0a395fb00c781391bbcbba2ee058fae2d205d67202c`.
- The beta.4 backup supplied the request texts. The outcomes above came from
  new official-release runs. This acceptance scope covers packaged backend
  APIs and local model inference. Desktop interaction has a separate
  acceptance step.

The official release manifest records `model_inference_tested=false` for its
release validation. The replay above adds a small, request-specific model
observation reviewed by the investigating agent. Independent formula review
and broader quality evidence continue under issue #46. The published package
identity is available in the
[v0.4.3 release and manifest](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.3).

## Decision

1. **Generate initial matrices from explicit parameters.** A stateless
   generator accepts validated matrix parameters and produces a LaTeX
   candidate. The first delivery covers general rectangular matrices and
   tridiagonal square matrices. The existing preset page supplies editable
   parameters and uses the current preview, copy, and insertion flow.
2. **Share generation across entry points.** A narrow natural-language
   recognizer extracts supported constraints from the original request before
   symbol substitution. Presets and recognized descriptions use the same
   parameter and generation contract. Partial recognition, conflicting
   constraints, and ambiguity remain visible in the bounded planner or
   review path. Original request constraints stay authoritative.
3. **Define dimensions and indices explicitly.** Support concrete and symbolic
   dimensions, bracket choice, index origin, and expanded or abbreviated
   presentation. An omitted tridiagonal order uses symbolic `n`. A concrete
   order of ten defaults to a full 10-by-10 expansion. Abbreviated display
   records logical dimensions and supported endpoint rules. Validate expansion
   limits and boundary orders such as one and two.
4. **Expose diagonal direction.** Default tridiagonal entries are
   `A_{i,i}=a_i`, `A_{i,i+1}=b_i`, and `A_{i+1,i}=c_i`, with all other entries
   zero. The UI labels the main, upper, and lower diagonals and their index
   origin. Explicit user directions determine the corresponding positions.
5. **Check the produced candidate.** Reuse SemanticDocument and the existing
   strict structural comparison capabilities to check supported dimensions,
   diagonal expressions, directions, index bounds, and band-exterior zeros.
   Full expansion permits cell-level checks. Abbreviated forms require a
   supported display contract with checkable endpoints and logical dimensions.
   Parameter provenance accompanies the result, while the check inspects the
   candidate itself.
6. **Bind constraint evidence to revisions.** Report `MATCH`, `DIFFERENT`,
   `UNSUPPORTED`, or `NOT_CHECKED` with the checked constraint scope and current
   revision. A known `DIFFERENT` enters the existing rejection or human-review
   path with diagnostics. A revised candidate requires fresh evidence before
   acceptance. FormulaState owns candidate adoption, and compile/render
   evidence belongs to the revision crossing the Commit Barrier.
7. **Keep outcome meanings explicit.** Request completion, formula validity,
   commit state, and request-constraint checks each retain their own meaning.
   The existing request-status and formula-validity distinction is documented
   in the data-backup contract. Fidelity checks report the portion of the
   request that they actually cover.

## Architectural fit

ADR-017 establishes the deterministic candidate shortcut and the original
request's authority. This decision extends that input seam with a bounded
matrix vocabulary. ADR-014 supplies stateless execution contracts, and
ADR-011 supplies FormulaState ownership and revision-bound evidence.
ADR-012 governs compact planner observations. The matrix check reports its
constraint summary through those observations.

ADR-015 governs edits to existing mathematical objects. This delivery
constructs initial matrix candidates. Its implementation belongs to the
existing candidate, semantic, and evidence layers, with focused additions to
the current preset page. The roadmap records this post-v0.4.3 slice and its
acceptance gates.

## Alternatives and tradeoffs

### Static LaTeX snippets

Static snippets give users an immediate starting formula. Their dimensions
and indexed patterns still require manual editing. Parameterized generation
was selected for the requested order and diagonal controls.

### Free-form generation followed by planner self-review

The current-release replay shows the planner finishing structurally incorrect
candidates after successful compilation. Deterministic generation and focused
constraint checks give the supported patterns repeatable behavior. The model
continues to handle requests outside that recognized vocabulary.

### A general matrix-editing framework

A general editor would need an operation model, broader UI design, and
additional semantic editing contracts. Initial-candidate generation provides
a bounded delivery that can be tested through current entry points.

The chosen approach adds a maintained vocabulary of matrix types and display
contracts. Symbolic dimensions and ellipses limit what can be established by
cell inspection, so the checker must publish its coverage. Request-specific
structural evidence supports fidelity review within that declared scope.

## Delivery and acceptance

The first implementation adds the preset form, `POST /api/matrix`, narrow
natural-language recognition, a shared matrix generator, and revision-bound
checks through the existing Agent Runtime. The commit records the matching
matrix evidence with compile and render evidence. Changed revisions require
their own constraint check. Recognized patterns use zero model calls, and
unrecognized matrix descriptions report their unchecked coverage in the trace.
The official v0.4.3 replay above remains the released baseline for comparison.

The review fixes give validated matrix generation a separate tool instance
with a 32768-character ceiling, matching the strict structure parser budget.
Formula validation, imported history formulas, and imported run-log formulas
share that ceiling. Model-proposed tool inputs use their 4000-character budget.
Matrix requests with nonempty supplemental context enter the planner path,
and candidate generation receives that context. Their matrix requirement
coverage is recorded as `NOT_CHECKED` with a planning reason.

Structured preset history uses the `matrix` input type. Reuse restores the
parameters into Presets, including legacy `nl` rows carrying the canonical
JSON source. Restoration invalidates previous and in-flight draft results.
Dimension recognition cleans trailing sentence punctuation while preserving
leading decimal points for the normal unsupported-input path.

| Priority | Issue | Layer and delivery role | Dependency |
|---|---|---|---|
| P1 | [#55 Parameterized matrix presets](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/55) | Input Layer / Deterministic Tools, shared generator and usable preset entry | Parameter contract precedes natural-language integration. |
| P1 | [#56 Natural-language matrix routing](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/56) | Input Layer / Deterministic Tools, recognized request constraints | Uses #55 and is accepted with #57. |
| P1 | [#57 Matrix constraint validation](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/57) | Semantic Layer / Evidence Layer / Commit Barrier, independent checks and regression cases | Check design proceeds alongside #55. Final acceptance covers both entry points. |
| P1 | [#59 Sum and integral fidelity](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/59) | Input Layer / Semantic Layer / Evidence Layer, separate quality track | Reuses the existing guard and review foundations. |
| P2 | [#58 Additional matrix types](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/58) | Input Layer / Deterministic Tools, diagonal, identity, zero, and triangular presets | Follows acceptance of #55 and #57. |

The first matrix delivery is accepted only after preset input, generation,
preview, copy/insertion, natural-language routing, and revision-bound checks
work together. Deterministic cases cover boundary orders, ten-by-ten full
expansion, symbolic dimensions, swapped diagonals, invalid parameters, wrong
indices, and nonzero entries outside the band. Legacy custom preset strings
and backup imports receive compatibility checks.

Current-release failure outputs become focused deterministic counterexamples.
Real-model replays run separately with recorded package and model identities.
Ordinary CI uses deterministic assertions under ADR-013. Necessary request
texts, output summaries, and run identities document the evidence, following
the repository's contribution policy for runtime data.
