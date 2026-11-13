# Baseline report — 2026-11-13

- Mode: **live**
- Model: `MiniCPM-V-4.7-1B`
- Golden entries exercised: 100

## Golden set

- Structural pass rate (anchor layer): 59/94 (62.8%)
- Entries with descriptive (non-machine-checkable) anchors: 3
- Compile layer: 91/100
- Render layer: 97/100
- Trace layer: 97/100

## Repair dataset (deterministic, brace-balance scope)

- Repair pass rate: 53/53 (100.0%)
- Latency p50 / p95: 2871 ms / 5439 ms

> Development-regression scope; not a general benchmark. See eval/known-gaps.md for measured boundaries.

## Errors

- 010: ComputationOutsideScope: TeXada 仅支持公式识别、转写和排版，不提供计算、化简、求解或证明。请描述要输入的公式；例如“输入 7+5”，或“输入 f(x) 的导数记号”。 TeXada transcribes and typesets formulas; calculation, simplification, solving and proofs are outside its scope. Describe the notation to enter.
- 062: ComputationOutsideScope: TeXada 仅支持公式识别、转写和排版，不提供计算、化简、求解或证明。请描述要输入的公式；例如“输入 7+5”，或“输入 f(x) 的导数记号”。 TeXada transcribes and typesets formulas; calculation, simplification, solving and proofs are outside its scope. Describe the notation to enter.
- 073: ComputationOutsideScope: TeXada 仅支持公式识别、转写和排版，不提供计算、化简、求解或证明。请描述要输入的公式；例如“输入 7+5”，或“输入 f(x) 的导数记号”。 TeXada transcribes and typesets formulas; calculation, simplification, solving and proofs are outside its scope. Describe the notation to enter.
