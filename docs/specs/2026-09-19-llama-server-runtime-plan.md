# Llama Server Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a built-in llama-server sidecar as the default local runtime: in-app start/stop, first-pull model download with progress, on-demand loading; Ollama and OpenAI-compatible remain selectable backends.

**Architecture:** `MiniCPMModel` already speaks OpenAI-compatible `/v1` only, so the migration adds a `LlamaServerManager` (same interface as `BackendManager`) that spawns one `llama-server` router process serving both models from `~/.texada/models/`, plus a streaming model downloader, FastAPI endpoints, frontend controls, and per-platform binary packaging. The three backends share one selection point and one readiness interface.

**Tech Stack:** Python 3.12, FastAPI, httpx streaming, asyncio subprocess, Tauri (Rust shell), PyYAML (existing), uv.

**Spec:** `docs/specs/2026-09-19-llama-server-runtime-design.md`

## Global Constraints

- No call site may branch on runtime identity; `config.active_base_url` / `active_model_name` / `active_vision_model_name` are the only seams.
- `reasoning_effort: none` for local MiniCPM5-2B text requests (v0.4.1 behavior) must hold identically on the llama-server path.
- The llama.cpp version is pinned (b9049 or later, required for MiniCPM-V 4.6) and validated at startup.
- Weights are never bundled into installers; acquisition is an explicit user action. Downloads use a `.part` suffix so interrupted downloads never masquerade as models.
- All existing tests must keep passing; `BackendManager` behavior for Ollama is unchanged.
- UI strings follow the existing bilingual (EN + 中文) pattern in `tauri-shell/src/main.js` and `index.html`.

## File Structure

New files:

- `src/texada/core/llama_server.py` — `LlamaServerManager`: process lifecycle, readiness probe (shared with `BackendManager`), model downloads with progress
- `src/texada/core/download.py` — streaming HTTP downloader with `.part` files, progress callbacks, HF mirror support
- `scripts/fetch-llama-server.sh` — download/pin the llama-server binary per platform for packaging
- `tests/test_llama_server.py` — manager unit tests (fake binary, mocked HTTP)
- `tests/test_model_download.py` — downloader tests (mocked streaming responses)

Modified:

- `src/texada/config.py` — three-value `backend`, llama-server fields, `active_*` mapping
- `src/texada/api.py` — start/stop/status/pull-progress endpoints
- `src/texada/core/backend.py` — extract shared readiness probe used by both managers
- `tauri-shell/src/main.js`, `tauri-shell/src/index.html` — third backend option, start/stop button, pull UI with progress
- `tauri-shell/src-tauri/tauri.conf.json` — `binaries/llama-server` externalBin entry
- `.github/workflows/release-desktop.yml` — fetch llama-server binary before build; notarization covers it
- `README.md`, `CHANGELOG.md`, `docs/architecture.md` — user-facing docs for the new default runtime

Responsibility split: `llama_server.py` owns process + model lifecycle; `download.py` is runtime-agnostic HTTP fetching; `config.py` is the single selection point.

---

### Task 1: Config extension

**Files:**
- Modify: `src/texada/config.py`
- Test: `tests/test_config.py` (extend)

**Interfaces:**
- Consumes: nothing new
- Produces: `backend: Literal["llama_server", "ollama", "openai_compatible"]` (default `llama_server`); `llama_server_host: str = "http://127.0.0.1:8080"`; `llama_server_binary: str = ""`; `llama_models_dir: str = ""`; `llama_context_size: int = 4096`; `llama_gpu_layers: int = 99`; `llama_models_max: int = 2`; `llama_idle_sleep_seconds: int = 300`; `active_base_url` returns llama host `/v1` when backend is llama_server; `active_model_name` / `active_vision_model_name` return `"text"` / `"vision"` routing names on llama_server; `backend_label` returns `"llama-server"` for run logs

- [ ] **Step 1: Write the failing tests** — extend `tests/test_config.py`: three backends selectable; `active_base_url` = `http://127.0.0.1:8080/v1` for llama_server; `active_model_name` = `"text"`; defaults unchanged for ollama/openai_compatible.
- [ ] **Step 2: Run to verify failure** — `uv run --extra dev pytest tests/test_config.py -q`; existing assertions for old defaults fail.
- [ ] **Step 3: Implement** — extend the Literal, add fields with env prefixes (`TEXADA_LLAMA_SERVER_HOST` etc., following the existing `normalize_ollama_host` pattern), update the three `active_*` properties and `backend_label`.
- [ ] **Step 4: Run to verify pass** — `uv run --extra dev pytest tests/test_config.py -q`.
- [ ] **Step 5: Commit** — `feat(config): three-value backend selection with llama-server default`

### Task 2: Shared readiness probe + LlamaServerManager core

**Files:**
- Create: `src/texada/core/llama_server.py`
- Modify: `src/texada/core/backend.py` (extract `probe_models_url`)
- Test: `tests/test_llama_server.py`

**Interfaces:**
- Consumes: `probe_models_url(base_url, headers)` extracted from `BackendManager._is_running`
- Produces: `LlamaServerManager(config)` with `async start() -> bool` (spawn `llama-server --models-dir <dir> --host --port --ctx-size --n-gpu-layers`, wait for `/v1/models` up to 60s), `async stop() -> bool` (SIGTERM, wait, SIGKILL fallback), `async ensure_ready() -> bool`, `async ensure_vision_ready() -> bool` (both model files present), `def get_status() -> dict` (running / models present / host), `def resolve_binary() -> Path` (explicit path → packaged path → `shutil.which`)

- [ ] **Step 1: Write failing tests** — `tests/test_llama_server.py`: `resolve_binary` precedence (explicit → PATH); `start` spawns a fake `llama-server` shell script that serves `/v1/models` after a delay (write the stub in `tmp_path`); `ensure_ready` false when binary missing (clear error); `ensure_vision_ready` false when mmproj file absent; `stop` terminates the process.
- [ ] **Step 2: Run to verify failure** — module missing.
- [ ] **Step 3: Implement** — process spawn via `asyncio.create_subprocess_exec`, readiness polling with the shared probe, model-file presence checks (`<dir>/MiniCPM5-2B-Q4_K_M.gguf` for text; vision pair for OCR), SIGTERM/SIGKILL lifecycle, startup version check (`--version` output must be >= b9049 — compare parsed build number, skip gracefully if unparseable).
- [ ] **Step 4: Run to verify pass** — `uv run --extra dev pytest tests/test_llama_server.py -q`; then full suite `uv run --extra dev pytest -q` (BackendManager refactor must not regress).
- [ ] **Step 5: Commit** — `feat(runtime): LlamaServerManager with shared readiness probe`

### Task 3: Model downloader

**Files:**
- Create: `src/texada/core/download.py`
- Test: `tests/test_model_download.py`

**Interfaces:**
- Consumes: httpx streaming
- Produces: `MODEL_CATALOG` (role → list of {filename, url, size_hint, mirror_url}); `async def download_model(role: str, dest_dir: Path, *, mirror: bool = False) -> AsyncIterator[dict]` yielding `{"file", "received", "total", "done", "error"}`; writes to `<file>.part`, renames on completion; refuses to overwrite an existing complete file

- [ ] **Step 1: Write failing tests** — mocked httpx stream (`respx`-free: monkeypatch `httpx.AsyncClient.stream`): progress events with monotonically increasing `received`; `.part` → final rename; error mid-stream leaves no complete file; existing file skipped.
- [ ] **Step 2: Run to verify failure** — module missing.
- [ ] **Step 3: Implement** — catalog for text (`MiniCPM5-2B-Q4_K_M.gguf` from `hf.co/openbmb/MiniCPM5-2B-GGUF`) and vision (`MiniCPM-V-4.6-Q4_K_M.gguf` + `mmproj-MiniCPM-V-4.6-F16.gguf` from `hf.co/openbmb/MiniCPM-V-4.6-gguf`), mirror variant via `hf-mirror.com`, chunked write with progress events, `.part` suffix, size verification when `Content-Length` present.
- [ ] **Step 4: Run to verify pass** — `uv run --extra dev pytest tests/test_model_download.py -q`.
- [ ] **Step 5: Commit** — `feat(runtime): streaming model downloader with progress and mirror support`

### Task 4: FastAPI endpoints

**Files:**
- Modify: `src/texada/api.py`
- Test: `tests/test_api.py` (extend)

**Interfaces:**
- Consumes: `LlamaServerManager`, `download_model`
- Produces: `GET /api/llama/status` → manager status dict; `POST /api/llama/start`; `POST /api/llama/stop`; `POST /api/llama/pull` (role, mirror) → SSE-style NDJSON progress stream or polling-friendly JSON events; endpoints exist only when `backend == "llama_server"`, otherwise 404 with a clear message

- [ ] **Step 1: Write failing tests** — with `backend="llama_server"`: status reflects a stopped manager; start/stop invoke the manager (monkeypatched); with `backend="ollama"`: endpoints 404.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — wire the manager into `create_app` alongside `BackendManager`; progress endpoint streams download events (NDJSON via `StreamingResponse`).
- [ ] **Step 4: Run to verify pass** — `uv run --extra dev pytest tests/test_api.py -q` and full suite.
- [ ] **Step 5: Commit** — `feat(api): llama-server lifecycle and model-pull endpoints`

### Task 5: Frontend controls

**Files:**
- Modify: `tauri-shell/src/main.js`, `tauri-shell/src/index.html`

**Interfaces:**
- Consumes: Task 4 endpoints; existing `settings.backend` select and status machine
- Produces: third backend option (`llama-server`, default); a start/stop button in the backend settings section; a "download models" button with per-file progress bars; status strings extended (`llama.loading`, `llama.missingModels`, `llama.stopped`, `llama.downloading`) in both languages

- [ ] **Step 1: Write the UI** — add option + i18n strings; fetch `/api/llama/status` on settings open; wire buttons; render progress from the NDJSON stream.
- [ ] **Step 2: Verify** — `node --check tauri-shell/src/main.js`; manual check impossible here, so assert the wiring via `tests/test_frontend_contract.py` conventions (the existing contract test pattern — check it and extend if it covers settings strings).
- [ ] **Step 3: Commit** — `feat(ui): llama-server backend controls and model download UI`

### Task 6: Packaging

**Files:**
- Create: `scripts/fetch-llama-server.sh`
- Modify: `tauri-shell/src-tauri/tauri.conf.json`, `.github/workflows/release-desktop.yml`, `scripts/macos-sidecar-entitlements.plist` (if needed), docs

**Interfaces:**
- Consumes: pinned llama.cpp release (b9049+)
- Produces: per-platform `llama-server` binary placed at `tauri-shell/src-tauri/binaries/llama-server` (with target-triple suffix per Tauri sidecar convention); release workflow step before `tauri-action`; notarization entitlement for executing the spawned binary (JIT/allowed execution on Apple Silicon)

- [ ] **Step 1: Write the fetch script** — map `uname -m` + OS to the llama.cpp release asset (macOS arm64/x64, Windows x64), verify SHA against a pinned list, fail loudly on mismatch.
- [ ] **Step 2: Wire the workflow** — add the fetch step to release-desktop.yml before the build; ensure `cargo check` in audit.yml does NOT require the binary (it only builds the shell).
- [ ] **Step 3: Verify locally** — run the script on this machine (macOS arm64), confirm the binary exists and `llama-server --version` reports a build >= b9049; `cd tauri-shell/src-tauri && cargo check` passes with the new externalBin entry.
- [ ] **Step 4: Commit** — `build: fetch pinned llama-server binary for desktop packaging`

### Task 7: Live verification and docs

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/local-model-benchmark-2026-09-12.md` (append) or a new `docs/local-model-benchmark-2026-09-19-llama-server.md`

**Interfaces:**
- Consumes: everything above; `eval/run_real_baseline.py --mode live`
- Produces: baseline report on the llama-server path; memory/cold-start/idle-unload measurements; user docs for the new default runtime

- [ ] **Step 1: Run the live baseline on llama-server** — start the manager against the downloaded binary, run `eval/run_real_baseline.py --mode live`, compare structural pass rate against the Ollama baseline 28/95 (29.5%).
- [ ] **Step 2: Record measurements** — dual-model memory (8GB machine), cold-start latency, idle-unload behavior, `reasoning_effort` equivalence spot-check.
- [ ] **Step 3: Write docs** — README quick start for the built-in runtime (new default), CHANGELOG Unreleased (EN + 中文), architecture.md backend section.
- [ ] **Step 4: Full validation and commit** — `uv run --extra dev --extra cas-eval --extra eval pytest -q`, ruff, `node --check`, `cargo check`; commit as `docs(runtime): publish llama-server baseline and user docs`.

## Definition of Done (spec §5 gates)

1. Live baseline on llama-server at or above the Ollama structural baseline; `reasoning_effort: none` equivalent.
2. Memory / cold-start / idle-unload measurements recorded with scope labels.
3. Release pipeline builds and signs/notarizes with the llama-server binary; `cargo check` green.
4. Full test suite green; zero call-site branching on runtime identity.
