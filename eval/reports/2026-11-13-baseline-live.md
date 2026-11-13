# Baseline report — 2026-11-13

- Mode: **live**
- Model: `MiniCPM-V-4.7-1B`
- Golden entries exercised: 100

## Golden set

- Structural pass rate (anchor layer): 59/95 (62.1%)
- Entries with descriptive (non-machine-checkable) anchors: 3
- Compile layer: 92/100
- Render layer: 98/100
- Trace layer: 98/100

## Repair dataset (deterministic, brace-balance scope)

- Repair pass rate: 53/53 (100.0%)
- Refused by the computation-scope gate (product boundary, not model failures): 2 (010, 073)
- Latency p50 / p95: 1548 ms / 4218 ms

> Development-regression scope; not a general benchmark. See eval/known-gaps.md for measured boundaries.
