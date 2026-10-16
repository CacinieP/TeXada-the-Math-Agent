# TeXada + Ollama b11669 local validation (2026-10-16)

Tested on Apple M4 / 16 GB / macOS 26.6.2, using the official MiniCPM-V 4.7 1B Q4_K_M and F16 projector from the earlier tests. Ollama is built from upstream commit `d919272`; its pin is b11669. This is a source-build result, not a claim about the installed Ollama release.

## Compatibility fix

The TeXada MiniCPM-V 4.7 profile previously sent `chat_template_kwargs.enable_thinking=false` to Ollama's OpenAI-compatible endpoint. Ollama ignores that field and maps `reasoning_effort=none` to `think=false`. A real request reached its token limit with zero final content and nonempty reasoning. The corrected request returned visible content without reasoning. Use `reasoning_effort=none` for Ollama text, planning, model completion, and OCR roles; retain the template option for the other existing profiles. Do not use hidden reasoning as final formula output.

The model and inference-fingerprint tests pass: 100 tests. All four inference roles are covered for the Ollama 4.7 profile and the existing compatible-provider profiles.

## Full source-backend runs

Same 100 clarified inputs and full-expression references, 8 synthetic OCR fixtures, and 6 completion inputs. Every request reached the actual local Ollama service through TeXada. Separate fresh application data directories were used before and after the fix.

| Check | Before fix | After fix |
|---|---:|---:|
| NL HTTP 200 | 100/100 | 100/100 |
| NL syntax-valid | 89/100 | 92/100 |
| NL strict structure MATCH | 46/100 | 53/100 |
| NL structure DIFFERENT / UNSUPPORTED | 39 / 15 | 32 / 15 |
| NL committed | 85/100 | 90/100 |
| Empty candidate model_request_failed | 4 | 0 |
| NL median wall time | 2.755 s | 1.154 s |
| OCR HTTP 200 / syntax-valid | 8/8 | 8/8 |
| OCR strict structure MATCH | 7/8 | 7/8 |
| OCR median wall time | 3.290 s | 1.141 s |
| Completion HTTP 200 / syntax-valid | 6/6 | 6/6 |

All OCR results remain pending review; none auto-committed. All six completion cases were deterministic, with zero provider calls, so they do not establish model completion quality. HTTP 200 is not task success: the before-fix run includes four runtime-guard failures returned in a successful HTTP response. Rendered HTML presence is not mathematical correctness. No invalid formula was committed, but 26 committed after-fix formulas differ from the strict references. Strict differences are not independent mathematical adjudication.

These are individual runs, with no explicit seed set by TeXada; latency/output differences are observations, not a statistical performance or accuracy claim. Candidate-first is enabled for this evaluation and remains opt-in.

## Released desktop check

Launched the retained v0.4.2-beta.3 macOS application with an isolated data directory and Ollama address. Its packaged backend returned HTTP 200 for two NL and two OCR requests. `x plus y` returned `x+y`; the fraction and integral image results were available for review. The old package still produced a squared norm for the vector 2-norm prompt. This confirms runtime availability, not correctness of that old package. The package was not rebuilt or replaced, and this was an API-driven check, not full UI acceptance.

## Scope

No model accuracy or human acceptance claim. Real pages, handwriting, Windows and 35B were not tested. Historical 0.40.3/0.40.4 projector failures remain valid for those versions. The original installed services and personal TeXada configuration were not replaced. Local test services were stopped after testing.
