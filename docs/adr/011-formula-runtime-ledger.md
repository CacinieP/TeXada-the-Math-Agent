# ADR-011: Formula Runtime Ledger

Status: Accepted

Date: 2026-08-25

Layer: Formula Runtime

Milestone: v0.4.0 Runtime Foundation

## Problem

The v0.3.8 Agent Runtime carries the authoritative formula in a local
`latest_latex` string. Tool observations can replace that string, and the final
guard can repair it again before returning. There is no durable identity for
the formula version a tool inspected. A successful compile of one value can
therefore be confused conceptually with a later rendered or repaired value.

This prevents TeXada from enforcing three required statements:

1. every accepted formula has a revision;
2. every formula evidence record belongs to one revision;
3. every commit proves the exact revision being returned.

## Decision

Introduce a planner-independent Formula Runtime with three append-only record
types:

- `FormulaRevision`: normalized LaTeX, monotonic number, parent revision, and
  mutation origin;
- `FormulaEvidence`: tool kind, success state, compact output, error, and the
  inspected revision;
- `FormulaCommit`: committed revision and the evidence records that crossed the
  barrier.

`FormulaState` is the only mutable authority. Every caller must provide its
expected revision when revising or committing. A stale expectation raises
`StaleRevisionError` and does not change state.

The first Commit Barrier is intentionally narrow: the current revision must
have successful `compile_tex` evidence whose output says `valid: true`, plus
successful `render_math` evidence. Evidence attached to parent revisions is not
eligible.

Planner Projection exposes only the current revision, LaTeX, commit state, and
compact evidence statuses. It does not expose the ledger's full evidence
payload or a mutable Semantic tree.

The existing Agent flow is migrated without removing existing public HTTP
fields or adding tools. Agent responses add `revision` and `committed`.
Planner/tool candidates become explicit revisions.
Final deterministic repair creates a new revision before recompile. Internal
`AgentRunResult` records revision, commit state, and a serializable ledger for
tests and the next API migration.

## Alternatives

### Keep `latest_latex` and add timestamps to observations

Rejected. Time ordering does not prove which formula value an observation
inspected, and concurrent or retried operations can still attach stale proof.

### Use a hash as the only formula identity

Rejected for the first implementation. A hash is useful for caching but does
not express parentage, ordering, stale-write checks, or user-visible history.
It can be added alongside revisions later.

### Persist the ledger in SQLite immediately

Deferred. v0.4.0 first establishes the in-memory contract per Agent run.
Persistence before the mutation and commit rules stabilize would freeze a
premature storage schema and mix Formula Ledger with the existing request Run
Ledger.

### Let tools own formula mutations

Rejected. Tools return observations or proposals; the Formula Runtime decides
whether a returned LaTeX value becomes a revision. This keeps deterministic
tools stateless and independently testable.

## Tradeoffs

- Agent runs retain more internal metadata than one `latest_latex` string.
- Existing planner calls that provide a new formula to an observational tool
  currently create an explicit revision. v0.4.1's state-bound argument binder
  can later remove this model-owned copying without changing the ledger.
- The first barrier recognizes only compile and render evidence. Reliability,
  visual fidelity, and future CAS evidence need separate policies rather than
  being inferred from a generic success flag.
- The initial ledger is run-local and is not yet an undo history or durable
  user document.

## Invariants

- Revision numbers start at 1 and increase monotonically within one state.
- A revision is immutable and points only to its immediate parent.
- Re-adopting identical normalized LaTeX is a no-op.
- Evidence cannot reference an unknown revision.
- Evidence is copied on write so later tool payload mutation cannot rewrite the
  ledger.
- Commit is idempotent for a revision.
- Commit rejects a stale expected revision.
- Compile and render evidence must both belong to the committed revision.
- Invalid or unrendered formulas may be returned for diagnosis, but they are
  never marked committed.

## Future

- Bind state-owned tool arguments from FormulaState rather than asking the 1B
  Planner to repeat current LaTeX.
- Keep the ADR-012 Planner Projection boundary stable as Tool contracts evolve.
- Add evidence policy types for OCR fidelity, visual round-trip checks, and
  reliability.
- Persist selected revision/commit records only after the v0.4 contract and
  privacy policy stabilize.
- Add semantic patches and anchors in v0.5 without changing revision identity
  or the Commit Barrier boundary.
