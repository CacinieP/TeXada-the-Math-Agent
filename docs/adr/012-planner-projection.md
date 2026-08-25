# ADR-012: Planner Projection

Status: Accepted

Date: 2026-08-25

Layer: Formula Runtime / Planner boundary

Milestone: v0.4.0 Runtime Foundation

## Problem

The v0.3.8 Planner receives compacted but still complete `SemanticDocument`
trees in Tool messages. That makes the model context a second, implicit copy of
formula state. It also spends small-model context tokens on source structure,
attributes, and nested children that the Planner does not need to select its
next action.

ADR-011 makes FormulaState authoritative, but that authority is incomplete if
the Planner continues to receive a full mutable-looking tree after every Tool
call.

## Decision

Separate evidence storage from model-facing observation:

- the Formula Ledger keeps compact Tool evidence bound to an exact revision;
- the execution trace keeps the diagnostic observation used for local audit;
- the Planner receives a bounded projection only.

The projection contains:

- Tool name, success state, error, and evidence revision;
- current FormulaState revision, LaTeX, commit state, and evidence statuses;
- ordinary scalar Tool outputs such as validity, diagnostics, repair method,
  Diff counts, mode, and export content;
- a Semantic summary containing parser backend, root kind, bounded node count,
  distinct kinds/roles, diagnostics, and a truncation flag.

The projection never contains a Semantic Unit `root` tree. Lists are capped at
32 items and Semantic traversal is capped at 64 nodes.

## Alternatives

### Continue sending the compact full tree

Rejected. Removing source spans and render payloads reduces size but preserves
the mistaken ownership model and worst-case nested context.

### Send only Tool success or failure

Rejected. The Planner still needs bounded structural facts, diagnostics, and
Diff outcomes to choose repair, render, or finalization.

### Ask MiniCPM5 to summarize the tree

Rejected. Projection is deterministic infrastructure. Paying another model
step to compress state would be slower, less reproducible, and unable to prove
size bounds.

## Tradeoffs

- Planner behavior may change because it no longer sees every nested unit.
- A future action may require one new projected field; that field must be added
  deliberately rather than exposing the full document again.
- Trace and Planner messages are no longer byte-identical, so tests must verify
  both the audit record and the model boundary.

## Invariants

- FormulaState is the sole formula authority; no `latest_latex` shadow state is
  kept in the Agent loop.
- Planner messages never contain a Semantic Unit `root` tree.
- Projection size is bounded independently of accepted input length.
- Every projected Tool observation includes its evidence revision and current
  FormulaState projection.
- Evidence remains richer than the Planner projection and stays locally
  auditable.

## Future

- v0.4.1 can bind state-owned Tool arguments so the Planner no longer repeats
  the current LaTeX in observational calls.
- Capability-specific projections may replace the shared projection after Tool
  execution contracts stabilize.
- OCR fidelity and future CAS evidence require their own explicit summaries;
  they must not reopen the full-tree boundary.
