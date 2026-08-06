# Why Deterministic Tools Matter In AI Agents

> LLM decides. Tools execute. Compiler verifies.

TeXada uses a small local model where judgment is useful and ordinary software
where correctness can be checked. MiniCPM5-1B can decide which operation to
perform next, but parsing, syntax validation, bounded repair, semantic diffing,
rendering, and export belong to independently testable tools.

## The Boundary

```text
User intent
    |
    v
MiniCPM5 planner
    |
    v
parse / compile / repair / diff / render / export
    |
    v
Observation
    |
    +----> planner continues, or
    |
    v
validated formula
```

This boundary matters for three reasons:

1. **A plausible answer is not a valid formula.** A model can emit convincing
   text with unbalanced groups or a downgraded operator. The compiler provides
   an explicit observation instead of relying on confidence.
2. **Repairs should be narrow.** Adding a missing closing brace is
   deterministic. Inventing an absent denominator is a semantic guess. TeXada
   performs the first and refuses to present the second as a guaranteed fix.
3. **Failures should be inspectable.** Each run records tool calls, latency,
   stop reason, formula validity, and the Agent trace. The same contract is
   used for natural language, OCR, and completion.

## Why A Small Local Planner

The planner does not need to memorize a LaTeX compiler. It needs to select a
small tool, read the observation, and decide whether another bounded step is
needed. That division makes a 1B local model useful without pretending it is a
proof engine.

High-confidence structured inputs may skip model inference entirely. They
still pass through the same compile and render tools, so "zero token" is an
acceleration path, not a bypass around validation.

## What TeXada Does Not Claim

TeXada validates supported TeX structure and guards selected semantic
invariants. It does not prove arbitrary mathematics, reconstruct unknown
intent from a badly damaged expression, or make every model-generated formula
correct. Users should still review mathematical meaning before publication.

See [Architecture](architecture.md) for the runtime contract and
[the recorded repair example](../examples/03-latex-repair/README.md) for a
concrete bounded repair.
