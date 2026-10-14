# Revision-bound Planner action surfaces

Issue #10 adds two Planner wire surfaces around the same canonical `ToolRouter`.
`planner_surface="full"` remains the default. `minimal` removes runtime-owned
`latex`, `before` and `after` arguments from inspection actions and only advertises
actions applicable to the turn's state. The canonical tools and their public
contracts are unchanged. A Planner-only `propose_candidate` is implemented by the
Formula Runtime, not inserted into `TeXToolset.DEFINITIONS`.

## Binding and action mask

Before each Planner call, Runtime freezes the current revision, candidate,
immediate parent and allowed actions. It provides that authority in the system
message and the wire schemas. Execution independently recompiles the live mask
and checks the proposal's revision. `compile_tex`, `parse_tex`, `render_math`,
`export` and `repair_tex` receive the Runtime's current LaTeX; `semantic_diff`
receives the immediate parent as `before` and the current revision as `after`.
Full-mode supplied values must equal those bindings. Minimal-mode supplied values
are rejected as extra arguments. A tool observation from an inspection action
cannot change formula state. Only the explicit proposal and deterministic repair
paths may revise it in this loop.

Both modes reject unknown actions, invalid arguments, inapplicable actions and
stale revisions before tool dispatch. A rejection returns an uncommitted result
with `stop_reason="planner_action_rejected"`, a typed code and the current action
state. Rejection does not invoke compatibility candidate generation or commit a
retained formula. Actions in the same batch continue to target the original turn
snapshot; after a proposal or repair creates a revision, later old proposals are
stale. They are never silently rebound to the new candidate.

The mask exposes parse/compile when a candidate exists, render/export only after
successful valid compile evidence for that exact revision, repair only after
successful invalid compile evidence, and diff only when an immediate parent
exists. Failed or previous-revision evidence cannot unlock an action. An invalid
candidate must use `repair_tex`, not a Planner proposal that repairs it directly.

Minimal mode requires explicit `expected_revision` on every action. Empty state
allows only `propose_candidate(latex, expected_revision=null)`; a bare final or
inspection parameter cannot seed state. For full-mode compatibility, a missing
revision is bound to the immutable turn snapshot and recorded as
`revision_source="runtime_turn_snapshot"`. Explicit revisions remain strict.
Full mode retains one empty-state `compile_tex(latex)` initial seed bridge,
recorded as `full_initial_seed_bridge` in the revision ledger and
`initial_seed_bridge=true` in the action bindings. This bridge cannot overwrite
an existing revision. Full also retains an empty-state direct-final seed, recorded
as `full_initial_final_seed_bridge`; it passes deterministic repair, anchor and
commit barriers. Both surfaces reject a different bare final once state exists:
the Planner must use `propose_candidate` with a valid turn snapshot. An identical
bare final can finalize the existing candidate. Host deterministic operator
restoration keeps its explicit runtime authority.
The action mask cannot establish that a candidate is mathematically faithful to
the original intent; separate strict references and mutation/review policies
address that question.

## Enable and revert

Set `TEXADA_PLANNER_SURFACE=minimal`, save `planner_surface` in config, or use:

```sh
curl -X POST http://127.0.0.1:18732/api/settings/backend \
  -H 'Content-Type: application/json' -d '{"planner_surface":"minimal"}'
```

The same API with `"full"` restores the full wire surface. Both modes retain
binding, mask and stale checks. Settings responses and data backup/import include
the flag; arbitrary values fail validation. The UI can use this API without
changing the canonical tool catalog. The inference identity integration records
the configured surface and actual Planner schemas separately.

## Paired evaluation

```sh
PYTHONPATH=src python eval/run_planner_surface.py \
  --output eval/reports/planner-surfaces-offline.json
```

Eight synthetic scenarios run under both surfaces as provisional NL candidate
synthesis, using the same authored action intent: explicit candidate workflow,
deterministic repair, parent/current diff,
unknown tool, bound-value override, stale inspection after mutation, bad render
option and state-inapplicable render. The scripted Planner translates only the
wire arguments. Validation, repair, parse, render and strict KaTeX whole-expression
comparison run locally. The evaluator isolates user credentials/settings, warms
the pinned parser and alternates pair order. The report includes submitted illegal
calls rejected, argument errors rejected, forbidden executions, completion rate
on positive cases, strict match/coverage, local Runtime latency and request/schema
bytes. Rejected negative cases are not counted as successful formula completions.
Protocol v2 records the task and explicitly leaves intent fidelity `NOT_CHECKED`.
It does not use an OCR task to authorize a changed recognized formula; OCR scope
and mandatory review have their own adversarial tests.

The checked-in replay has 8/8 expected outcomes per surface, 3/3 completed positive
cases with full-structure matches, five rejected illegal proposals and zero
forbidden executions per surface. This is execution-boundary evidence from a small
authored set, not general model-quality evidence or independent human approval.
Provider token use and inference latency are `NOT_CHECKED` because no live model
was sampled. Request bytes cannot be converted into token claims. Local elapsed
times cannot be used to claim model speed. The default stays `full` until paired
live sampling shows a benefit without structural or completion regression.

Validation: adversarial binding/mask tests, real compile/repair/render workflows,
settings rollback and paired-report tests, plus the existing Runtime/API suite.
The original standalone surface branch passed **690 tests**, with **8 external
E2E tests skipped**. After integrating mutation scopes, protocol v2 retains
full/minimal schema bytes of **46,193 / 19,827**, and measures request bytes of
**108,353 / 81,871**. These measurements apply only to this authored offline set.
