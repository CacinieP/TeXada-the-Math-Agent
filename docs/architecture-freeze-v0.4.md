# TeXada Architecture Freeze — v0.4 to v1.0

Status: Active

Frozen on: 2026-08-25

Current milestone: v0.4.0 Runtime Foundation

This document freezes TeXada's core architectural vocabulary. New code must fit
one layer and serve the active milestone. A change that cannot answer both
questions is deferred rather than turned into another core abstraction.

## Permanent Layers

```text
User
  ↓
Input Layer
(NL / OCR / Completion)
  ↓
Formula Runtime
(FormulaState / Revision / Ledger)
  ↓
Semantic Layer
(SemanticUnit / Diff / Patch)
  ↓
Evidence Layer
(Compile / Render / Visual / Reliability)
  ↓
Planner
(MiniCPM5-1B)
  ↓
Deterministic Tools
  ↓
Commit Barrier
```

The diagram declares ownership, not a requirement that every request execute
every box once in that visual order. Formula Runtime owns state throughout the
bounded Planner/Tool loop. Tools emit revision-bound evidence; only the Commit
Barrier may mark a revision as committed.

## Change Gate

Every issue and pull request must state:

1. Which permanent layer owns the change?
2. Which active milestone does the change complete?

The v0.4 series does not accept a new public tool, OCR provider, model role, or
major UI redesign. Those changes belong to later milestones or a separate
architecture decision.

## Milestones

| Version | One problem to solve | In scope | Explicitly deferred |
|---------|----------------------|----------|---------------------|
| v0.4.0 | Runtime is the sole state authority | FormulaState, Revision, Ledger, Planner Projection, Commit Barrier | New tools, OCR upgrades, model changes, UI redesign |
| v0.4.1 | Tools expose stable runtime contracts | Capability Probe, schema validation, affordance policy, execution contract | Semantic editing |
| v0.5 | Edits target mathematical objects | Semantic Patch, SourceSpan, Semantic Anchor, Scope Guard | OCR intelligence |
| v0.6 | OCR preserves perception evidence | Raw Observation, Visual Verification, Hole, Clarification | Learning loop |
| v0.7 | Corrections become reusable data | Run Trace, Correction, Promotion, Benchmark | Capability platform |
| v1.0 | Products depend on capabilities, not model names | Planner/OCR/Editing capability contracts and stable benchmarks | Unscoped framework expansion |

## v0.4.0 Invariants

- Every accepted non-empty formula has a monotonic revision.
- Revisions form an append-only parent chain; a no-op does not create a new
  revision.
- Every formula evidence record names the exact revision it inspected.
- Evidence for an older revision never proves a newer revision.
- A mutation or commit with a stale expected revision is rejected.
- Commit requires successful compile and render evidence for the current
  revision.
- Planner observations are compact projections; the Planner does not become
  the owner of a full mutable Semantic tree.
- Finalize may propose a deterministic repair, but the repaired LaTeX becomes a
  new revision before it can be recompiled or committed.

## Current Implementation Slice

The v0.4.0 implementation is governed by
[ADR-011](adr/011-formula-runtime-ledger.md) and
[ADR-012](adr/012-planner-projection.md). FormulaState now owns every accepted
candidate, Tool evidence is revision-bound, Planner messages use bounded
Semantic summaries instead of full trees, and commit requires compile/render
evidence for the current revision. Agent APIs expose `revision` and `committed`;
the six-tool surface remains unchanged.
