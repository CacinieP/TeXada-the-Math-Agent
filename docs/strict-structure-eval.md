# Strict whole-expression structure evaluation

This optional evaluation compares an output with explicitly authored **complete
LaTeX references**. It supplements the existing anchor-containment diagnostic;
it does not change Agent behavior, formula commit rules, or the math tools.
Neither original natural language nor a partial golden-set anchor is converted
into a reference AST.

Tracked by [M1 / issue #7](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/7).

## Result contract

| Status | Meaning |
|---|---|
| `MATCH` | Both complete expressions are supported and their entire ordered canonical structures match. |
| `DIFFERENT` | Both are supported, but a role, value, ordered child, scope, delimiter or dimension differs. |
| `UNSUPPORTED` | Comparison was attempted, but parsing, representation, normalization or resource limits prevent a reliable verdict. |
| `NOT_CHECKED` | No explicit full reference was supplied, or no candidate is available after an inference error. |

`MATCH` is notation-structure agreement with an authored reference, **not a
proof of mathematical equivalence or fidelity to an ambiguous NL request**.
Syntax, rendering, commit status, provider errors and latency remain separate.
A model output that contains every anchor can still have added terms or changed
scope, and can therefore pass containment while being structurally `DIFFERENT`.

## Supported normalization and coverage

`eval/structural_match.py` uses the pinned KaTeX 0.17.0 raw AST. It does not use
the tolerant fallback or the product's lossy `SemanticDiffer.equivalent` as an
oracle. A node-type and field allowlist rejects unsupported or newly introduced
AST representations instead of silently flattening them.

The canonical tree retains ordered expression children; fraction numerator and
denominator; root index and radicand; script base, subscript and superscript;
operator lower and upper bounds; array row/column roles and dimensions; font and
accent markers; and exact delimiters. Fraction bars and binomial delimiters are
retained, so `\binom{n}{k}` cannot pass as `\frac{n}{k}`.

Approved presentation normalization removes math spacing, sizing/style/color
wrappers and transparent braces. The approved `le/leq/≤` and `ge/geq/≥` aliases
are canonicalized; other symbols retain their parsed form. Ordinary explicit
parentheses/brackets are grouped before
scripts bind; `(x+1)^2` therefore matches `\left(x+1\right)^2` while remaining
different from `x+1^2`. This resolves the G-001 notation pair for this separate
strict evaluator without weakening the legacy containment matcher.

Text nodes, invisible/geometry wrappers such as phantom and smash, unknown
macros/nodes/fields, unresolved placeholders, custom macro definitions, array
partition lines, ragged arrays, invalid syntax and guarded excessive input are
`UNSUPPORTED`. Equal unknown commands or equal parse failures cannot produce
`MATCH`. Source locations are not compared; arbitrary algebraic simplification,
commutativity and automatic implicit/explicit multiplication equivalence are
not implemented. Allowed alternative notations must be listed explicitly.

## Running and interpreting the report

The live runner is unchanged unless the reference flag is supplied:

```sh
TEXADA_OPENAI_API_KEY=... uv run --no-sync python eval/run_minicpm_v47.py \
  --output-dir /path/to/evidence --structure-references eval/structure_references.yaml
```

Each row retains `anchor_containment` and adds independent `strict_structure`
status, reason, canonical tree hashes, parser/normalization version, matched
reference ID, provenance/review labels and first difference path. The report
saves the SHA256 of the exact registry bytes loaded before inference, rather
than rereading a potentially changed file. Without the flag, every row is
`NOT_CHECKED`; partial or descriptive
anchors never silently become full references.
Strict-evaluator time is recorded separately; the legacy runtime/containment
latency boundary is preserved for existing paired comparisons.

The summary shows all four counts, total rows, attempted rows, comparable rows,
the match fraction among comparable rows, and comparable coverage among all
rows. Always present the counts and coverage beside that fraction: unsupported
and missing-reference cases are not successful cases, and a small comparable
subset is not a model quality result for the full dataset.

`structure_references.yaml` initially contains eight authored full-expression
cases and explicitly approved notation alternatives. Every entry is labeled
`synthetic_author_reference` and `agent-reviewed`. These are **not independently
human-verified NL ground truth**. Extending this registry requires an explicit
reference, provenance and review status; evaluation must not generate its own
references from the outputs it is judging.

`structural_adversarial_cases.yaml` contains 20 complete expression pairs with
reasons, expected matcher status and proposed review verdicts. They test the
deterministic evaluator; they are synthetic author references with agent review,
not measured model outputs or a completed independent human assessment.

```sh
uv run --no-sync pytest tests/test_structural_match.py tests/test_anchor_match.py
```

These tests need no inference API. They cover the paired fixture set, known
lossy collisions, parser/coverage failure, reference provenance and alternatives,
denominators, and optional live-report integration with mocked inference.
