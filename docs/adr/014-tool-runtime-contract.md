# ADR-014: Tool Runtime Contract

Status: Accepted

Date: 2026-09-19

Layer: Planner / Deterministic Tools boundary

Milestone: v0.5 design phase (supersedes the v0.4.1 milestone row)

## Problem

The architecture freeze lists v0.4.1 as "tools expose stable runtime
contracts": Capability Probe, schema validation, affordance policy, and an
execution contract. None of these exist in the source. v0.4.1 shipped the
MiniCPM5-2B model switch and fixes instead, leaving the milestone row as a
silent drift.

Writing those contracts now, without a consumer, would produce speculative
interface work. But the v0.5 semantic patch work needs exactly these
contracts: a patch is a structured tool-adjacent artifact whose allowed
operations, argument schema, and failure semantics must be defined before
any patch code exists.

## Decision

Merge the v0.4.1 tool-contract work into the v0.5 design phase. The v0.4.1
milestone row is marked superseded rather than treated as delivered. The
contracts are specified in reverse from what the patch model needs:

1. **Capability probe.** Each tool declares its capability statement
   (what it can prove, what it cannot). The Agent exposes probes so callers
   and tests can assert tool availability before planning.
2. **Schema validation.** Every tool call argument is schema-validated
   before execution. Invalid arguments produce a typed error observation,
   never a silent fallback.
3. **Affordance policy.** A per-tool declaration of the operation set the
   planner may request. This policy is the direct input to the v0.5 Scope
   Guard: the guard restricts patches to declared affordances.
4. **Execution contract.** Deterministic tools remain stateless. They return
   observations or proposals; the Formula Runtime decides whether a returned
   value becomes a revision (per ADR-011). Tools never mutate formula state.

Ordering rule: affordance policy is derived from the ADR-015 patch model's
required operations, so ADR-015 is written first and ADR-014's policy
section cites it.

## Alternatives

### Ship a v0.4.2 that implements the four contracts as frozen

Rejected. The contracts have no consumer until v0.5. Speculative contracts
get rewritten the first time a real patch needs an operation they excluded.

### Drop the contracts from the roadmap entirely

Rejected. Schema validation and affordance policy are prerequisites for
patch safety, not optional polish. Deferring them to v0.5 implementation
would mean designing the guard and the patch simultaneously.

### Fold contracts into the six existing tools silently

Rejected. The freeze's change gate requires each change to name its layer and
milestone. Silent contract growth inside tools breaks testability and the
ADR trail.

## Tradeoffs

- The v0.4.x series never fully closes its frozen milestone table. The
  roadmap records this openly instead of retro-labeling v0.4.1.
- ADR-014 depends on ADR-015 for its affordance content, so the two must be
  reviewed together.
- Contract work lands without a user-visible release in Iteration 2. Its
  value is entirely in Iteration 3's patch safety.

## Invariants

- Tools stay stateless and deterministic; the execution contract never moves
  mutation authority out of the Formula Runtime.
- Affordance policy is a declared, testable list per tool; the Scope Guard
  may only be narrower than declared affordances, never wider.
- Schema validation failures are typed observations visible in the trace.
- No new public tool is added by this ADR; the six-tool surface stays
  unchanged.

## Future

- Capability-specific planner projections replace the shared projection once
  execution contracts stabilize (carried from ADR-012).
- Evidence policy types for OCR fidelity and reliability attach to the same
  contract surface.
- Persistence of ledger records remains deferred until the mutation and
  commit rules stabilize (carried from ADR-011).
