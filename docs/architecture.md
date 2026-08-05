# TeXada Architecture

Version: v0.3.8. TeXada is an on-device, agent-driven structured
math editor. It is not a LaTeX input method with an LLM bolted on.

TeXada has exactly two model roles:

- `MiniCPM5-1B`: text generation, planning, tool selection, and state control.
- `MiniCPM-V 4.6`: image understanding and formula OCR.

Parsing, validation, repair, diffing, rendering, and export are deterministic
software tools. In particular, `repair_tex` is not a model endpoint.

## System Overview

```text
Image / Keyboard
        |
        v
    OCR / Input
        |
        v
MiniCPM5-1B Planner
        |
        +--> parse_tex
        +--> compile_tex
        +--> repair_tex (deterministic rules)
        +--> semantic_diff
        +--> render_math
        +--> export
        |
        v
    Observation
        |
        +----> MiniCPM5 decides whether to call another tool
        |
        v
Structured final formula
```

The primary loop is `Planner → Tool → Observation → Planner`. Its state is a
`SemanticDocument`, so the stronger invariant is `Semantic Unit → Tool →
Semantic Unit`. Natural language, OCR, and completion all converge on this
runtime; `/api/convert` remains a non-Agent compatibility route for older
clients.

| Product path | Model role | Agent loop |
|--------------|------------|------------|
| Natural language (`/api/agent`) | Deterministic candidate or MiniCPM5-1B planner | Yes |
| OCR (`/api/ocr`) | MiniCPM-V 4.6 candidate → MiniCPM5-1B planner | Yes |
| Completion (`/api/complete`) | rule/MiniCPM5 candidate → MiniCPM5-1B planner | Yes |
| Validation (`/api/validate`) | Deterministic local code | No model |

“Agentized” does not mean every request must spend a model inference. Before
MiniCPM5 is invoked, a deliberately narrow deterministic candidate engine may
recognize an explicit trailing LaTeX hint or an unambiguous structured pattern
such as `求k从1到n的k平方`. The candidate still goes through `compile_tex` and
`render_math`, and both calls remain visible in the Agent trace. Invalid or
operator-drifting candidates fall back to the normal MiniCPM5 planner loop.
This preserves the Planner/Tool contract while making exact structured inputs
effectively instant.

OCR and completion do not become separate autonomous agents. Each first
produces a candidate, then the shared runtime executes `compile_tex` and gives
that real Observation to the sole MiniCPM5 planner. The planner can select
repair, diff, and render tools; the final runtime guard still compiles, repairs
when needed, and renders deterministically. All three responses expose the same
semantic document, semantic diff, trace, and stop reason fields.

The OCR input contract is deliberately narrow: one image contains one primary
formula. Page layout analysis and multi-formula segmentation are outside this
product path; users should crop a page or collage before recognition.

Two guard levels are intentionally combined rather than substituted:

```text
SymbolEngine
    -> MiniCPM5 Planner / TeX Tools
    -> Level 0 OperatorDriftGuard (operator presence/downgrade; retry on failure)
    -> Level 1 Semantic Diff (normalized structure, when a reference exists)
    -> Validator / Deterministic Fixer / Render
```

Level 0 keeps the original repository's fast substring/rank check and feeds a
failed anchor back into the bounded planner loop. If all planner turns still
drift, the original intent-specific constrained generation path gets one final
attempt and is adopted only when every pinned operator is present. For the
narrow `integrand 在区域 D 上` integral form, a final deterministic template
may restore an authoritative SymbolEngine integral rank after the 1B model
returns prose, a full LaTeX document, or an empty retry. Level 1 does
not pretend that raw natural language is a reference AST: it runs for explicit
before/after formulas, repairs and edit operations where both semantic
documents exist.

## Agent Runtime

The runtime lives in `src/texada/agent/`.

- `MiniCPMModel.plan()` submits normal OpenAI function definitions.
- SGLang with `--tool-call-parser minicpm5` returns OpenAI `tool_calls`.
- Ollama and other local endpoints may return MiniCPM5's native XML directly.
  TeXada parses the official
  `<function name="..."><param name="...">...</param></function>` format.
- The runtime never introduces a second agent wire protocol.
- `agent_max_steps` defaults to 3. An identical repeated tool call and two
  consecutive tool errors trip a deterministic circuit breaker.
- Render mode values are normalized case-insensitively, and a successful
  `render_math` observation ends the planner loop immediately; the runtime
  guard still validates the final formula.
- A final runtime guard always compiles, repairs through `repair_tex` when
  needed, and renders the result even after a planner circuit breaker.
- `PlannerBackend` is a deliberately narrow code seam; MiniCPM5 remains the
  production implementation rather than a promise of generic model parity.
- The Agent path reuses `SymbolEngine` and the extracted
  `OperatorDriftGuard`; it does not bypass the original anti-drift behavior.

MiniCPM5 is the planned and tested planner contract. Generic OpenAI-compatible
configuration is retained as a migration bridge, not as a promise that every
model will reproduce MiniCPM5's agent behavior.

## TeX Tools

The tools live in `src/texada/tools/`. Each has one responsibility and an
independent test surface.

| Tool | Responsibility |
|------|----------------|
| `parse_tex` | Parse LaTeX into a semantic unit tree |
| `compile_tex` | Validate structure and run the local KaTeX compile check |
| `repair_tex` | Repair common syntax defects with deterministic local rules |
| `semantic_diff` | Compare fraction, root, operator, bounds and script units |
| `render_math` | Produce KaTeX HTML or highlighted LaTeX |
| `export` | Produce bare, inline, display or Markdown output |

## Semantic Units

`src/texada/semantic/` runs the pinned KaTeX 0.17.0 parser in a reusable,
in-process V8 context provided by `mini-racer`. It maps the KaTeX AST to the
smaller structures TeXada needs to reason about: fractions, roots, integrals,
summations, products, limits, scripts, groups, matrices, commands and symbols.
Malformed input and unsupported custom macros fall back to a tolerant recovery
parser, while preserving the KaTeX diagnostic. The adapter isolates KaTeX's
internal `__parse` API so a pinned-version upgrade has one test surface.
The same context also performs backend rendering and validation, with
`\placeholder` registered as a controlled `\square` macro on both Python and
browser paths. FastAPI closes the V8 context during lifespan shutdown so a
stopped sidecar does not leave a worker process behind.

Semantic diff paths describe units such as `denominator`, `lower_bound` and
`superscript`; they are not character offsets. Syntax repairs are recorded as
semantic `syntax` changes when a malformed group becomes valid.

The diff algorithm is a role-aware weighted ordered-tree edit:

1. Canonical subtree fingerprints prune semantically identical branches,
   including presentation-only spacing differences.
2. Unique mathematical roles such as `numerator`, `denominator`, `subscript`
   and `upper_bound` are matched before positional children.
3. Remaining ordered children use dynamic-programming alignment; edit costs
   are higher for fractions, roots, operators, scripts and environments.
4. The observation contains an edit script, weighted cost, normalized distance,
   semantic similarity and the same `[0, 1]` value as `reward`.

## Experimental CAS Capability Boundary

`src/texada/cas/` is an optional developer capability (introduced in v0.3.2,
still unregistered as of v0.3.8), not a seventh public TeX tool. It is not
imported by the Agent, API, desktop UI, or bundled sidecar. The default
release behavior and installer dependency set therefore remain unchanged.

The production direction is deliberately one-way:

```text
Pinned KaTeX AST → TeXada Semantic Unit → whitelist translator → SymPy core
```

Raw ANTLR/Lark LaTeX parsing appears only in evaluation probes. The translator
rejects any unit outside the declared scalar subset before starting a
comparison. Results separate status from evidence basis/grade and record
assumptions, exact finite witnesses, task seed, SymPy/policy versions, and
cache identity.

Potentially non-terminating work runs in one reusable spawned worker. Every task
resets SymPy's random seed; the parent enforces a deadline and a PID-based RSS
ceiling, then kills and recreates the worker after a violation. The
cross-platform policy does not rely on `RLIMIT_AS`.

`eval/cas_capabilities.yaml` is the machine-readable source of truth.
`docs/sympy-capability-matrix.md` is generated from it. No `algebra_check`
registration should occur until the supported matrix continues to observe zero
false verified results and the product exposure is reviewed separately.

## Deterministic Repair

`src/texada/core/repair.py` is the implementation behind `repair_tex`.
It wraps the existing `LaTeXFixer`, revalidates every candidate, and returns a
Semantic Diff describing what changed. It repairs bounded syntax problems such
as unbalanced braces and environments; it does not claim to reconstruct an
arbitrary mathematically wrong formula.

There is no TeX2TeX checkpoint, Transformers repair backend, repair-model
configuration, or third inference path in this product. A future model-repair
research project must live outside TeXada and may only return through an
explicit product decision, not through a dormant adapter.

## Endpoint And Desktop Layers

The local Ollama port is not fixed. The default is
`http://localhost:11434`, but users can change it with the Settings UI,
`~/.texada/config.json`, or `TEXADA_OLLAMA_HOST`.

The FastAPI address and the Ollama address are separate layers. `TEXADA_API_HOST:TEXADA_API_PORT` is where the desktop shell reaches TeXada's own `/api/*` routes. Release installers bundle this FastAPI backend as a PyInstaller sidecar and start it automatically when the API is not already reachable. `TEXADA_OLLAMA_HOST` is where the FastAPI backend reaches local model APIs and appends `/v1` internally. They should not be set to the same port unless a custom proxy intentionally combines both roles.

## Backend Modules

| Module | Responsibility |
|--------|----------------|
| `config.py` | Pydantic settings from `~/.texada/config.json` plus `TEXADA_` environment variables |
| `api.py` | FastAPI app factory and HTTP endpoints |
| `sidecar.py` | Packaged FastAPI entry point used by desktop installers |
| `agent/runtime.py` | MiniCPM5 planning and multi-step observation loop |
| `agent/protocol.py` | Official MiniCPM5 XML / OpenAI tool-call normalization |
| `tools/` | Single-purpose TeX tool registry and router |
| `semantic/` | Semantic math unit parser and structural diff |
| `core/router.py` | Routes natural language, completion, OCR, and shorthand requests |
| `core/backend.py` | Checks local Ollama or cloud endpoint readiness |
| `core/model.py` | OpenAI-compatible chat wrapper for text and vision models |
| `core/validator.py`, `core/fixer.py`, `core/repair.py` | Validation and deterministic repair |
| `render/engine.py` | KaTeX and LaTeX highlighting |
| `store/` | Result history, request-level run logs, and custom preset persistence |

## Run Ledger And Data Portability

Every executable API path receives a unique `run_id`. Successful outputs use
the same ID in conversion history; failures remain visible in the run ledger
with status code and error details. Agent runs additionally persist the
planner trace, tool names, tool-call count, stop reason, latency, and tokens.
OCR records metadata only and never stores uploaded image bytes.

The list endpoint returns paginated summaries and omits the potentially large
trace payload. The UI fetches full detail only when a row is expanded, and
shows request success separately from formula validity. Run-log retention is
unlimited by default; positive day/item caps opt into cleanup.

The design adapts CC Switch's request-ledger principles—success/error symmetry,
indexed filters, request detail, and portable backups—to an on-device math
agent. It does not copy provider billing fields that TeXada does not need.
`history.db`, `runs.db`, and `shorthands.json` remain separate stores so users
can export/import results, diagnostics, and presets independently. Full backup
schema v2 contains all three plus non-sensitive settings.

Clipboard, paste and notifications are handled in the Tauri shell for desktop builds. The old Python platform adapter layer was removed because it was no longer used by the API or installer builds.

## Models

| Role | Default | Notes |
|------|---------|-------|
| Local planner | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | Planning, tool selection and fallback completion |
| Local vision | `openbmb/minicpm-v4.6:latest` | OCR for handwritten or screenshot formulas |
| Compatibility | User-provided OpenAI-compatible endpoint | Migration path; MiniCPM5 is the runtime contract |

MiniCPM5 can emit the answer in a `reasoning` field with empty `content`, so
the model wrapper falls back to extracting LaTeX from either field. For tool
calling, SGLang is the preferred production runtime; the Ollama/GGUF path is
kept for on-device accessibility and raw XML compatibility.

## Frontend

The active UI lives in `tauri-shell/src/` and has no build step.

- Tabs: NL, OCR, completion, snippets, history, settings.
- Settings persist UI language, UI zoom, local Ollama host, local model names and cloud model credentials.
- History has separate Result and Run Log views. Results can be reused or copied; logs use paginated summaries, can be filtered by operation/status, and lazily load request detail and Agent trace when expanded.
- Settings can export/import full backups or independently manage result history, run logs, and custom presets.
- Formula blocks type into the current system cursor in desktop mode; copy buttons still copy.
- Header and neutral panel surfaces call the Tauri native `start_dragging` command; form controls, tabs, formula blocks and other interactive targets are excluded so IME composition and clicks remain stable.
- Browser development falls back to clipboard copy for insert-at-cursor behavior.

## Desktop Shell

The release desktop shell is Tauri only:

| Path | Role |
|------|------|
| `tauri-shell/src-tauri/` | Rust shell, tray icon, global shortcut, native clipboard, window drag and bundle config |
| `tauri-shell/src/` | Static frontend bundled into the Tauri app |
| `scripts/build-windows-app.ps1` | Windows local NSIS build helper |
| `scripts/build-backend-sidecar.py` | Builds the real PyInstaller backend sidecar for release or a stub for `cargo check` |
| `scripts/generate-app-icons.py` | Rebuilds the source PNG, macOS ICNS, Windows ICO and Tauri PNG icons |
| `.github/workflows/release-desktop.yml` | macOS arm64 DMG, macOS Intel DMG and Windows x64 NSIS release build |

The old Swift WKWebView shell and v1 prototype archive were removed because they were not part of the release build and duplicated current code paths.

## Configuration

Persistent config lives at `~/.texada/config.json`. Environment variables override config values.

Important variables:

| Variable | Purpose |
|----------|---------|
| `TEXADA_BACKEND` | `ollama` or `openai_compatible` |
| `TEXADA_OLLAMA_HOST` | Local Ollama base URL, any host/port |
| `TEXADA_MODEL_NAME`, `TEXADA_VISION_MODEL_NAME` | Local text and vision model names |
| `TEXADA_OPENAI_BASE_URL` | Full OpenAI-compatible cloud base URL |
| `TEXADA_OPENAI_MODEL_NAME`, `TEXADA_OPENAI_VISION_MODEL_NAME` | Cloud text and vision model names |
| `TEXADA_OPENAI_API_KEY` | Cloud provider API key |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI bind address |
| `TEXADA_API_BASE` | Explicit desktop shell API base |
| `TEXADA_DISABLE_BUNDLED_BACKEND` | Disable automatic sidecar startup for custom backend management |
| `TEXADA_API_TIMEOUT_SECS` | Tauri API request timeout |
| `TEXADA_INFERENCE_TIMEOUT_SECONDS`, `TEXADA_API_REQUEST_TIMEOUT_SECONDS` | Backend model and API request timeouts |

## CI And Release

- `Audit`: Ruff, pytest (including pinned `cas-eval` capability tests),
  pip-audit, npm audit, JS syntax check and Tauri `cargo check` on macOS and
  Windows. The Rust check creates a generated backend stub only to satisfy
  Tauri `externalBin` resolution.
- `Desktop Release`: runs pre-release audit, builds the real PyInstaller FastAPI sidecar, builds signed and notarized macOS DMGs plus the Windows NSIS EXE, and publishes the official release assets.
- The release sidecar installs only the `dev` extra. Because no runtime module
  imports `texada.cas`, optional SymPy/psutil/ANTLR/Lark/PyYAML dependencies are
  not bundled into desktop installers.
- macOS signing and notarization are controlled by repository secrets only. The workflow expects `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_TEAM_ID`, `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER_ID`, and `APPLE_NOTARY_KEY`; personal certificate contents are not documented in the repo.
- Source-run shell launchers and macOS LaunchAgent templates are intentionally not kept; packaged desktop releases are the supported user path.

## Current Cleanup Policy

Tracked source should describe one current app. Generated caches, local dependencies, archives, stale prototypes and compiled binaries are not kept in git.
