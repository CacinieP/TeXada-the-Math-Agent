# ADR-017: MiniCPM-V 4.7 Single Checkpoint Profile

Status: Accepted for opt-in adaptation; Q4 quality evaluation pending

Date: 2026-10-13

Layer: Planner / OCR model deployment

Baseline: `main` at `5c9c13e`

## Problem

TeXada previously deployed MiniCPM5 for text planning and MiniCPM-V 4.6 for
image recognition. The next iteration must use `MiniCPM-V-4.7-1B` for both
roles while retaining the deterministic math tools and Formula Runtime.
API-based local development and a later local Q4 deployment need to share
the same application contract.

The previous two-role decision is recorded as
[ADR-006 in Design Evolution](../design-evolution.md#adr-006产品只保留两个模型角色).
Its deployment detail names two checkpoints. Its substantive decision removes
the repair model and assigns repair to deterministic tools. This ADR
supersedes the checkpoint count for the new profile and preserves that repair
boundary.

## Decision

1. Opt in through `scripts/run-minicpm-v47.sh`. The launcher selects the
   existing `openai_compatible` backend and sets both text and vision model
   names to `MiniCPM-V-4.7-1B`. Conflicting role names are rejected before
   launch. Legacy defaults and saved user settings remain compatible.
2. Use `https://api.modelbest.cn/v1` for adaptation. The launcher requires
   `TEXADA_OPENAI_API_KEY` in the environment. Keys are never embedded in the
   launcher, example configuration, documentation, or reports.
3. An externally managed local Q4 server can replace the endpoint with
   `http://127.0.0.1:8080/v1`. It must expose the alias
   `MiniCPM-V-4.7-1B` for both roles. An unauthenticated server can use the
   non-secret `local-no-key` placeholder. This changes transport and precision,
   not the model-role boundary. It does not establish equivalent Q4 quality.
4. Keep OCR and Planner as distinct responsibilities. OCR proposes a candidate;
   Planner selects bounded actions using real Tool Observations. A shared
   checkpoint does not authorize OCR to own FormulaState or replace tools.
5. Preserve FormulaState revision authority, revision-bound evidence, bounded
   Planner Projection, tool runtime contracts, the ledger, and the compile /
   render Commit Barrier defined by ADR-011 through ADR-015. Existing safety
   budgets and user review remain in force.
6. For NL input, keep the deterministic candidate shortcut, then have the
   same checkpoint propose LaTeX before the first Planner tool decision.
   The profile enables `nl_candidate_first`; other profiles default to off.
   Original request anchors remain authoritative. Generation and its retry
   share the original request deadline, and every candidate enters the
   existing compile intake before bounded Planner review. This prevents the
   common failure of sending Chinese instructions directly to a TeX parser.
7. The V4.7 profile uses color-preserving PNG normalization for OCR (`raw`).
   Legacy profiles retain binary preprocessing by default. In the 12-image
   synthetic ablation, thresholding/upscaling lost a root index and introduced
   a malformed nested fraction. Raw does not certify visual fidelity: the
   same model still downgraded a double integral in every preprocessing mode.

The initial paired 20-case smoke test measured 3/19 anchor containment with
full-schema Planner initialization, 14/19 in narrow candidate generation,
and 11/19 in the final candidate-first runtime. The final run had 17/20
syntax/render/commit successes and three provider content-policy errors.
These are development acceptance observations, not general quality claims.

The adaptation is based on merged `main` at `5c9c13e`. The separate local
runtime platform work in PR #4 / ADR-016 is not a merge dependency. This
profile reuses the endpoint configuration already supported by main; it does
not claim to implement the bundled llama-server lifecycle or first-download
UI described by ADR-016.

## Alternatives

### Change global defaults immediately

Deferred until the new profile has measured regression evidence. An opt-in
launcher makes the requested iteration reproducible without rewriting
existing users' backend configuration.

### Keep a second text model as a fallback

Rejected for this iteration. Both text and vision requests must use the same
checkpoint. Failures stay visible and are handled by the existing bounded
runtime and deterministic tools.

### Require the bundled local runtime migration first

Rejected as a dependency. API adaptation uses the existing backend and can
produce model-behavior evidence before the platform runtime changes.

## Validation and Limits

- Launcher contract tests prove that both role names are identical, external
  local endpoints remain configurable, caller working directories are
  irrelevant, missing keys fail early, and error output does not reveal keys.
- Config tests cover the existing fallback from an empty OpenAI vision model
  name to the text model name. The launcher explicitly sets both names.
- Live API evidence, native tool-call behavior, OCR fidelity, regression
  outcomes, and latency must be reported separately from launcher tests.
- Q4 requires its own runtime compatibility and formula-quality evaluation
  before being presented as a validated local deployment.
