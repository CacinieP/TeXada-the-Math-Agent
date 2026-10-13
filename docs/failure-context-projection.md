# Failure context projection

Implements [issue #9](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/9).
`failure_context_projection` defaults to true; set it false in saved configuration
or `TEXADA_FAILURE_CONTEXT_PROJECTION=false` for the raw-history control.
`eval/run_minicpm_v47.py --raw-failure-context` exposes the same paired switch.

Before every Planner call, the runtime makes a separate view of the audit
messages. Failed calls and their observations are removed together. A compile
result with `ok=true, valid=false` is a validation failure. Mixed turns retain
successful pairs and clear assistant prose which might contain failed arguments.
Missing, duplicate, malformed and orphaned observations are handled conservatively.
The raw conversation and `trace.raw_tool_calls` remain available for audit.

The recovery view contains host-selected failure kinds, recovery actions and the
current FormulaState projection. It never copies raw errors or argument blocks
into recovery summaries. An invalid formula can remain the authoritative current
formula until it is repaired; deleting that state would destroy the recovery task.
This feature does not grant permission to mutate state or choose arbitrary tools.

Each trace records the mode, removed failures, authoritative revision, request
JSON byte count, and provider-reported prompt tokens when available. Absent token
usage is `NOT_CHECKED`; JSON bytes are not substituted for token counts. Stable
inference identities include Planner controls; schema-1 identities without those
controls preserve their original digest when imported.

`PYTHONPATH=src:eval python eval/compare_failure_context.py --output report.json`
replays three public trajectories in both modes using the same scripted proposals
and real local tools. It compares recovery, repeated proposals, rounds, strict
structure and local latency; it issues zero model requests. The replay is a
regression experiment, not evidence of better model reasoning or faster APIs.
