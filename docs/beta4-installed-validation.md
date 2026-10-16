# v0.4.2-beta.4 installed-package validation

Date: 2026-10-16. Mac mini M4, 16 GB, macOS 26.6.2. Release source commit `1329999162eaa22d17ac5f4198450ee09af9f1ab`.

All release CI jobs passed: 1064 Python tests, 13 skipped; 24 frontend tests; macOS/Windows Rust checks; Windows owned-process tests; release audit; macOS arm64/Intel signed and notarized builds; Windows NSIS build and installation smoke.

The actual arm64 DMG was mounted locally and its app copied into an isolated installation. Deep signature and notarization ticket validation passed. The bundle reports beta.4 and contains llama.cpp build 11669. Models came from the same verified official 1B Q4_K_M + F16 projector files used in the earlier tests; the desktop owned the inference process. Personal configuration and installed Ollama were not replaced.

## Installed built-in backend

- NL: 100/100 HTTP 200, 90/100 API workflow `valid=true`, 89 committed; strict structure MATCH 50, DIFFERENT 34, UNSUPPORTED 16. Median request time 1.081 seconds.
- OCR: 8/8 HTTP 200, 7/8 API workflow `valid=true`, strict structure MATCH 7/8. No OCR auto-commits. Median request time 2.294 seconds.
- Completion: 6/6 valid deterministic cases, zero provider calls; no model completion-quality claim.
- The vector two-norm case produced `\lVert x \rVert_2`, not a squared norm.
- One integral OCR result compiled successfully and matched its reference, but the model requested unsupported export format `bare`; the runtime rejected that action and retained a pending review. The failed first-pass outcome is preserved in the evidence.

`valid` describes the overall workflow and must not be labeled as a pure LaTeX syntax metric. Each tested OCR candidate had successful compile evidence, even though one later planner action was rejected. HTTP success, render HTML, commit state and strict AST matching are separate measurements. Twenty-eight committed NL formulas differ from strict references; these are not independently adjudicated mathematical errors or correctness scores.

## Installed Ollama path

The packaged application was switched to the isolated b11669 Ollama source build. Six NL and two OCR requests returned HTTP 200 with no empty formulas. Every recorded inference call used `reasoning_effort=none`. Readiness changed from unverified/unverified to verified/verified after real text and OCR inference. Sequence-limit and paired-set outputs that failed semantic guards remained uncommitted; successful inference is not mathematical correctness.

## Release scope

No installer/startup/runtime loading regression was found. Preserve the existing semantic and planner guards, human review and Beta status. This is not evidence of general mathematical correctness, handwritten/real-page OCR, or Windows/Intel live-model performance. The checks launch the actual native app and exercise its packaged backend via HTTP; they are not full UI click-through acceptance.

See `ollama-b11669-validation.md` for source before/after reasoning-control measurements. The source Ollama and installed built-in runs are distinct and must not be combined into a single accuracy result.
