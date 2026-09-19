# ADR-015: Semantic Patch Apply Model

Status: Accepted

Date: 2026-09-19

Layer: Semantic Layer / Formula Runtime boundary

Milestone: v0.5 (edits target mathematical objects)

## Problem

v0.4 makes FormulaState the sole formula authority, but the Planner still
produces whole-formula LaTeX strings, and the deterministic path repairs via
`repair_tex`. An edit to "just the numerator of this fraction" cannot be
expressed, validated, or bounded. The v0.5 milestone requires edits to target
mathematical objects, which means a structured edit artifact with explicit
targeting, explicit scope, and explicit failure semantics.

The design question is who produces the structured edit. A 2B planner is
better at constrained structured output than at free-form LaTeX rewriting,
but it must not become an unconstrained editor.

## Decision

Adopt a hybrid patch model:

1. **The planner produces patches, not formulas.** A patch is a structured
   object: target (Semantic Anchor + SourceSpan), operation (from the
   ADR-014 affordance set), and payload. Patches are schema-validated before
   execution.
2. **A deterministic applier applies patches.** Application resolves the
   anchor against the current revision's Semantic tree, applies the
   operation, and serializes back to LaTeX. The applier never calls a model.
3. **The Scope Guard bounds every patch.** A patch may only request
   operations declared in the ADR-014 affordance policy. Out-of-scope
   operations are rejected before application.
4. **Failure is explicit.** A patch either produces a new revision (which
   must cross the commit barrier with compile and render evidence per
   ADR-011) or is rejected with a typed stop reason. There is no path where
   a failed patch silently returns the original formula.
5. **Deterministic fallback stays.** When patch production or application
   fails within the bounded loop, the existing `repair_tex` path remains the
   fallback, and `direct_repair_blocked` continues to force repairs through
   the tool surface.

## Alternatives

### Planner selects an edit intent; a deterministic editor generates the patch

Rejected for v0.5. Intent-only selection limits edits to a predefined
operation vocabulary that cannot express partial rewrites (e.g., replacing a
summand). The vocabulary can be layered on top of the patch model later.

### Planner rewrites the full LaTeX, then semantic_diff verifies

Rejected. That is the v0.4 model with a verifier bolted on. It cannot
express "edit only this subtree", wastes small-model context, and gives the
Scope Guard nothing to bound.

### Patches mutate FormulaState directly on application success

Rejected. ADR-011's commit barrier requires compile and render evidence for
the current revision. A patch that bypasses the barrier would reintroduce
exactly the state authority problem ADR-011 solved.

## Tradeoffs

- The planner gains a new structured output format; its prompts, schema, and
  tests change, and recorded-mode golden set fixtures from Iteration 1 must
  be re-recorded for patch turns.
- Anchor resolution needs SourceSpan fidelity from the Semantic Layer; spans
  that do not survive KaTeX normalization force conservative rejection.
- The applier adds a serialization step (Semantic tree back to LaTeX) that
  must be semantically faithful; diff-based verification (semantic_diff) is
  the accepted guard, not a proof.
- Small models will produce malformed patches often; the typed rejection
  path and repair fallback are the mitigation, and their frequency is a
  baseline metric to watch in Iteration 3.

## Invariants

- A patch never mutates FormulaState directly; it proposes, the applier
  resolves, and the commit barrier decides.
- Every applied patch creates a new revision whose parent is the pre-patch
  revision; a no-op patch creates no revision.
- Scope Guard rejection and anchor resolution failure produce typed stop
  reasons visible in the trace.
- The repair fallback and `direct_repair_blocked` behavior are unchanged.
- Semantic identity of the surrounding formula outside the patch target is
  verified by semantic_diff before the patched revision may be committed.

## Future

- An intent layer (named edit operations) can sit above the patch model once
  patch reliability is measured.
- Semantic Anchor stability across revisions enables correction reuse in
  v0.7.
- Affordance policy (ADR-014) may widen after v0.5 measurements show which
  operations the planner requests and which it misuses.
