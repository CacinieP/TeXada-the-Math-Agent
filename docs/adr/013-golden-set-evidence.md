# ADR-013: Golden Set Evidence

Status: Accepted

Date: 2026-09-19

Layer: Evidence Layer (cross-cutting quality track)

Milestone: Quality track (serves v0.5-v1.0; not a v0.x milestone)

## Problem

TeXada has no quantitative usability evidence anywhere in the repository. The
README records a latency measurement from 2026-07-07 and v0.4.1 records a
six-case development set, but no pass rate, recall, or repair rate exists.
This creates three concrete problems:

1. Comparison with Mathpix, Overleaf, and ChatGPT is a product-focus
   declaration, not a data-backed claim.
2. The v0.5 semantic patch work has no regression gate. A patch that
   structurally alters a formula cannot be proven safe without a before/after
   invariant set.
3. Behavior-affecting changes such as the runtime migration in ADR-016 have
   no way to prove neutrality.

A manual test prompt list already exists (`docs/test-prompts-100.md`, 100
entries with expected key structures and a five-item manual checklist). The
gap is automation and measurement, not collection.

## Decision

Establish a cross-cutting evidence track with two deliverables:

1. **Golden set.** A parameterized pytest golden set generated from
   `docs/test-prompts-100.md` (100 entries across 8 categories). Four
   assertion layers:
   - structural anchor: anchor and output are normalized through the existing
     Semantic Layer (KaTeX AST to SemanticUnit kinds) and the anchor kind
     sequence must appear as a subsequence of the output. This absorbs
     equivalent spellings (whitespace, `\left`/`\right`, `\dfrac`/`\frac`).
     Failures are triaged into a known-gaps list rather than silently
     accepted;
   - compile: the in-process pinned KaTeX 0.17.0 compiles the output;
   - render: `render_math` succeeds;
   - observability: the agent trace is expandable and `run_id` lands in the
     run log store.

2. **Repair dataset.** ~50 typical broken LaTeX inputs (missing groups,
   dropped limits, `\iiint`-to-`\int` degradation). Fully deterministic:
   after `repair_tex`, both compile and render must pass. This dataset runs
   in regular CI because it needs no model.

Two execution modes with a hard boundary:

- **Recorded mode** (default, regular CI): no model calls. Recorded planner
  turns drive the runtime, and the golden set validates pipeline
  invariants - guard behavior, commit barrier, revision monotonicity, and the
  compile/render/observability assertions on recorded outputs. This gate
  answers "given this model output, is the pipeline correct".
- **Real mode** (`--extra eval`, manual or tag-triggered): a real local model
  runs the golden set and produces baseline numbers. This gate answers "is
  the product usable". Real-mode runs never gate CI.

Baseline numbers (NL structural pass rate, repair pass rate) are written to
`eval/reports/` and cited in README and comparison.md with an explicit
non-general-benchmark scope statement, following the v0.4.1 precedent.

## Alternatives

### Keep manual prompt checking

Rejected. Manual checking produced no numbers, does not regress, and cannot
gate the v0.5 semantic work.

### Put real-model runs in CI

Rejected. CI has no Ollama/llama-server; model runs would be permanently red.
Mixing "guards correct" with "product usable" pollutes both gates.

### Collect a new 200-500 entry corpus first

Rejected. The 100-entry list with semantic anchors is already the seed corpus
and its assertion dimensions are defined. Collecting more prompts before
automating the existing ones delays measurement without adding evidence.

### OCR recall baseline in this iteration

Deferred. No annotated image corpus exists. OCR evidence belongs with the
v0.6 perception-evidence milestone.

## Tradeoffs

- The golden set in recorded mode does not measure model quality; teams must
  not read a green recorded-mode run as a product quality signal.
- Structural anchor matching via subsequence may pass a formula whose anchor
  appears in an unintended position. The known-gaps list and later
  structural-containment upgrade are the accepted cost of an MVP.
- The evidence track adds a test asset outside the frozen milestone table.
  The roadmap documents it as a cross-cutting track for this reason.
- Baseline numbers create an obligation: every later iteration must not
  regress them. That is the point.

## Invariants

- The golden set and repair dataset are append-only regression assets;
  changing an assertion requires a new ADR.
- Recorded mode never calls a model; real mode never gates CI.
- Every baseline report states its scope (model, date, entry count) and
  declares itself not a general benchmark.
- Golden set automation must not change any `src/texada` runtime behavior
  (bug fixes allowed, recorded in CHANGELOG).

## Future

- Upgrade anchor matching from subsequence to structural containment.
- Add OCR recall baseline when annotated material exists (v0.6).
- Add a "why changed" export (semantic diff explanation plus tool timeline)
  reusing run-log data.
- Feed recorded planner traces from real runs as adversarial fixtures
  (mini-model bad outputs) to harden deterministic repair.
