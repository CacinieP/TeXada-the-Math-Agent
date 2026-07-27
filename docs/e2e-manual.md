# TeXada Local E2E Manual

This checklist validates the primary desktop/browser flow after the Agent
Runtime migration.

## 1. Prepare the model

```bash
ollama pull hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M
ollama serve
```

If Ollama is already running, the second command will report that the port is
in use; keep the existing process.

For the production-quality native tool-call path, use MiniCPM5-1B through
SGLang with `--tool-call-parser minicpm5`, then select OpenAI-compatible mode in
TeXada Settings. Ollama remains the easiest local E2E route and TeXada parses
raw MiniCPM5 XML when it is exposed in response content.

## 2. Start the backend

From the repository root:

```bash
uv sync --extra dev
uv run texada serve
```

Wait for Uvicorn to listen on `http://127.0.0.1:18732`.

## 3. Start the browser UI

In a second terminal:

```bash
python3 -m http.server 1420 --directory tauri-shell/src
```

Open [http://localhost:1420](http://localhost:1420).

## 4. Human test cases

1. In the NL tab enter `0 到 1 上 x 平方的积分`.
   - A rendered integral appears.
   - The source badge reads `MiniCPM5 Agent`.
   - `Agent 执行轨迹` expands and shows planner/tool steps.
   - The final runtime step includes `compile_tex` and `render_math`.

2. Enter `二重积分 f(x,y) 在区域 D 上`.
   - The final LaTeX is structurally equivalent to
     `\iint_{D} f(x,y)\,dx\,dy`, never a downgraded `\int`.
   - The first trace step includes the deterministic preprocessed input.
   - If MiniCPM drops the integral rank/domain or leaks prose such as
     `in region D`, `operator_drift_guard` restores this narrow,
     SymbolEngine-anchored structure without another model call.

3. Enter `a 除以 b 的分数`.
   - The result contains `\frac`.
   - Expanding the trace shows semantic/tool observations rather than a plain
     model-only conversion.

4. Enter `x 下标 i 改成上标 i`.
   - The result contains an upper script.
   - If a change was produced through tools, the trace summary reports semantic
     edits; semantic paths use roles such as `superscript`, not character
     offsets.

5. Switch between KaTeX and pure LaTeX with `Command/Ctrl + K`.
   - Rendering switches without another model request.

6. Copy the LaTeX and Markdown forms.
   - Bare LaTeX and `$$...$$` output remain correct.

7. Open `History`, then switch between `Result history` and `Run logs`.
   - The successful NL request appears in both views with the same `run_id`.
   - The Agent row is marked `agent` / `planner`.
   - The row displays request status separately from formula validity.
   - The initial list response contains a lightweight summary without `trace`;
     expanding a row fetches latency, tokens, stop reason, tool names, and the
     full trace on demand.
   - After more than 40 matching rows exist, `Load more` appends the next page.
   - OCR and completion rows are marked `ocr` / `planner` and
     `completion` / `planner`; both contain candidate-intake and runtime-guard
     tool calls and a non-empty trace.

8. In Settings -> Data, verify all four groups.
   - Full backup includes `history`, `run_logs`, `shorthands`, and safe
     `settings`, with `_meta.schema_version = 2`.
   - Result history, run logs, and custom presets each export independently.
   - Re-importing the same files in the UI uses merge mode and reports zero
     new duplicate rows on the second import.
   - Built-in presets cannot be replaced by a preset import.
   - API keys and OCR image bytes never appear in any exported JSON.
   - Run logs are retained without a default time/item cap. Positive
     `TEXADA_RUN_LOG_MAX_DAYS` or `TEXADA_RUN_LOG_MAX_ITEMS` values opt into
     automatic cleanup.

## 5. API-level evidence

```bash
curl -s http://127.0.0.1:18732/api/agent \
  -H 'content-type: application/json' \
  -d '{"text":"a divided by b","render_mode":"katex"}'
```

The JSON response must contain:

- `source: "agent"`
- `semantic_document`
- `agent_trace`
- `stop_reason`
- `run_id`
- valid final `latex`

Then inspect the correlated ledger row:

```bash
curl -s http://127.0.0.1:18732/api/runs/<run_id>
```

For the NL path, `operation` is `agent`, `model_role` is `planner`, and
`trace` is non-empty. `/api/complete` and `/api/ocr` return the same Agent
fields. Their first trace item is `candidate_intake`, their last item is
`runtime_guard`, and their run-log role is also `planner`. The OCR log's model
name records the `MiniCPM-V 4.6 → MiniCPM5-1B` chain.

## 6. Automated gates

```bash
uv run ruff check .
uv run pytest
node --check tauri-shell/src/main.js
python scripts/build-backend-sidecar.py --mode stub
cargo check --manifest-path tauri-shell/src-tauri/Cargo.toml
```

Live-model HTTP tests can be enabled after the API is running:

```bash
TEXADA_RUN_E2E=1 uv run pytest tests/test_e2e.py -q
```
