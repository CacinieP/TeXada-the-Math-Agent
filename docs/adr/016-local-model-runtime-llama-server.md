# ADR-016: Local Model Runtime (llama-server)

Status: Accepted

Date: 2026-09-19

Layer: Planner (model runtime infrastructure)

Milestone: v0.4.3 platform track (outside the frozen v0.5 milestone table)

## Problem

The local runtime is Ollama. Users must install Ollama separately, pull
models with CLI commands, and manage the daemon outside the application. The
existing `BackendManager` auto-starts `ollama serve` as a subprocess but
offers no in-app stop, no in-app model acquisition, and no way to release
model memory when idle. Ollama inside a Docker Desktop container on macOS
provides no GPU acceleration, and the application cannot control that
situation.

Both models have official GGUF releases suitable for llama.cpp: the text
model (`openbmb/MiniCPM5-2B-GGUF`, already in use) and the vision model
(`openbmb/MiniCPM-V-4.6-gguf`, with `mmproj-MiniCPM-V-4.6-F16.gguf`, merged
into llama.cpp mainline in PR #22529). Recent llama-server supports router
mode: one process hosts multiple models, routes by the request's `model`
field, loads models on demand (with per-request autoload control), and
unloads idle models. This is exactly the "pull once, load on demand"
behavior requested.

## Decision

Adopt a dual-runtime architecture:

1. **Built-in llama-server sidecar is the default local runtime.** One
   `llama-server` process in router mode hosts both models. The application
   starts and stops it in-app (start/stop control plus an extended status
   machine: Ready / Loading / Model missing / Stopped / Disconnected).
2. **First-pull UI inside the application.** Settings offers one-click
   download of the GGUF weights (and mmproj for the vision model) into
   `~/.texada/models/`, with progress, cancellation, and an HF-mirror option
   for CN networks. Installers bundle the `llama-server` binary only, never
   the weights.
3. **A `LlamaServerManager` mirrors the `BackendManager` interface**
   (`ensure_ready`, `ensure_vision_ready`, `get_status`). All call sites
   already speak OpenAI-compatible `/v1`, which keeps the migration surface
   small.
4. **Ollama and OpenAI-compatible remain selectable backends.** Existing
   users' `ollama_host` configuration and cloud settings are unaffected.
   Settings exposes three choices: built-in llama-server (default), Ollama,
   OpenAI-compatible.

Sequencing rule: this migration ships in Iteration 1.5 (v0.4.3), after the
Iteration 1 golden set exists. The golden set's real-mode baseline is the
only gate that can prove the runtime swap is behavior-neutral.

## Alternatives

### Add start/stop UI to the Ollama path only

Rejected. It is cheap but leaves the external-install dependency, the
Docker-without-GPU situation, and the inability to unload idle models. It
solves the control symptom, not the dependency.

### Remove Ollama entirely

Rejected for now. It breaks existing user configuration and forfeits the
compatibility escape hatch during a behavior-sensitive migration. Removal
can be reconsidered after the llama-server path has a measurement history.

### Bundle a Python inference runtime (e.g., llama-cpp-python) in-process

Rejected. In-process inference inside the FastAPI sidecar couples model
memory to the backend process, complicates the existing request timeouts,
and loses router-mode multi-model lifecycle management.

## Tradeoffs

- Installers grow by the `llama-server` binary per platform (macOS aarch64 /
  x64, Windows x64); the macOS notarization flow must sign it.
- First-run model download (~1.6 GB total for the vision path) adds a
  network-dependent setup step with failure modes the app must surface.
- On-demand loading trades cold-start latency (roughly 10-15 s first load
  per model, per MiniCPM deployment docs) for released idle memory; the
  unload policy needs measurement on 8 GB machines against the existing
  A18 Pro baseline.
- Two runtimes mean two status/probe code paths to keep in sync.

## Invariants

- The three backends share one selection point and one readiness interface;
  no call site branches on runtime identity.
- `reasoning_effort: none` for local MiniCPM5-2B text requests (v0.4.1
  behavior) must hold identically on the llama-server path.
- Deterministic tools, the Formula Runtime, and the commit barrier are
  runtime-independent; this ADR changes no layer below Planner.
- The llama.cpp version is pinned (b9049 or later required for MiniCPM-V
  4.6) and recorded in the build configuration.
- Weights are never bundled into installers; acquisition is an explicit
  user action.
- Downloaded weights are accepted only when their SHA-256 matches the value
  pinned in the catalogue. A right-sized but wrong-content file — the failure
  mode of any interrupted or mis-assembled chunked transfer — is re-downloaded,
  never loaded: a silently corrupted `MiniCPM5-2B-Q4_K_M.gguf` reproduces as
  degenerate output (`content` filled with repeated filler tokens), not as an
  error.

## Future

- Slot/context tuning (default 4096) measured against the 90 s inference
  timeout before v0.4.3 ships.
- Ollama branch removal reconsidered after measurement history exists.
- Model catalogue in-app (quantization choice) once a single model per role
  is proven stable.
