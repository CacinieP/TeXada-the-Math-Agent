# v0.4.2-beta.2 validation

The beta integrates both previously separate PR stacks. Local fixes were first
submitted to PRs #19, #25 and #26; the integration resolves the API, runtime,
inference identity, single-model alias and installer differences.

## Benchmark scope

Apple M4, 16GB, Metal, MiniCPM-V-4.7-1B Q4_K_M and F16 projector; llama.cpp
b11609; temperature 0.1, seed 47, context 8192, one slot, reasoning off.
The text benchmark enables `TEXADA_NL_CANDIDATE_FIRST=true`. This is an explicit
evaluation configuration; the existing candidate-first setting remains opt-in.

The clarified 100 cases have complete reviewed answers and domain assumptions
in `eval/structure_references.yaml`; the source prompts are preserved in
`eval/golden_set.yaml`. Seventeen inputs were clarified before the final runs.
Equivalent expressions count when the entire mathematical meaning and task
requirements are preserved. The model was never given the reference answers.

Whole-formula correctness: 75/100. Full correct-and-committed: 59 to 74/100;
minimal: 71/100. Full also commits 24 wrong formulas; commit success and syntax
validity are not mathematical correctness. One correct full result remains
bound to human review. The independent exploratory supplement scores 9/20;
it is hand-authored, not random population sampling. Adjudication is by Codex,
without independent human verification. A generic completeness prompt was
rejected after two regressions and no improvement on the supplement.

## Release gates

The final integration must pass Python, frontend, native Rust and Windows
owned-process checks. Windows must execute the NSIS installer in a clean temporary installation.
Hosted macOS CI copies the retained signed `.app` into a clean temporary
installation; DMG mounting has failed in that environment, so the local M4
additionally mounts and installs the real arm64 DMG. Each native application
must start its bundled backend and render a deterministic formula.
The bundled runtime build must be 11609. macOS assets must be signed, notarized
and stapled; the arm64 installer is additionally exercised on the local M4.
Windows native CI installation is recorded separately from local macOS tests.

The workflow creates a draft beta, preserving v0.4.1 as the stable latest.
Public publication occurs after artifact verification. Windows installers
are unsigned. macOS requires 13.3 or newer, matching the pinned runtime Mach-O
minimum deployment target. Native smoke scripts do not download model weights or establish
mathematical accuracy; local inference is measured separately.
