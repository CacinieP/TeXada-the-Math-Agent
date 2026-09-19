# Golden Set Evidence I Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the existing 100-entry manual test prompt list into a pytest golden set with a 50-entry deterministic repair dataset, producing the project's first baseline numbers.

**Architecture:** A one-shot generator parses `docs/test-prompts-100.md` into a committed YAML fixture. Assertions reuse the Semantic Layer (KaTeX AST → SemanticUnit kinds); the anchor matcher checks subsequence containment, which absorbs equivalent spellings. Recorded planner turns (captured from a real model run) drive the runtime in regular CI; a separate live script produces baseline numbers. The repair dataset is fully deterministic and runs in CI without a model.

**Tech Stack:** Python 3.12, uv, pytest (asyncio auto mode), PyYAML, the project's existing `TeXadaAgentRuntime` / `TeXToolset` / `SemanticParser`.

**Spec:** `docs/specs/2026-09-19-golden-set-evidence-i-design.md`

## Global Constraints

- KaTeX is pinned at 0.17.0 (vendored, in-process). Never add a browser dependency.
- No `src/texada` runtime behavior changes in this plan. Bug fixes are allowed only with a CHANGELOG entry.
- All commands use `uv run --extra dev --extra eval ...`. The `eval` extra adds only `pyyaml>=6.0.2,<7` (Task 7 creates it; Tasks 1-6 run with `--extra dev` plus a local `PYTHONPATH=eval` or run after Task 7 — order: run Task 7's pyproject edit early, see Task 1 Step 0).
- Tests follow the existing pattern in `tests/test_agent_runtime.py`: construct `TeXadaAgentRuntime(config, model=...)` and set `runtime.backend.ensure_ready = AsyncMock(return_value=True)`.
- pytest runs with `asyncio_mode = "auto"` (pyproject `[tool.pytest.ini_options]`); async tests need no decorator.
- Every baseline report and README/comparison number must carry the scope disclaimer: development-regression scope, not a general benchmark (v0.4.1 precedent).

## File Structure

New files:

- `eval/generate_golden_set.py` — one-shot markdown-table parser → `eval/golden_set.yaml`
- `eval/golden_set.yaml` — committed fixture: `{entries: [{id, category, input, anchor}]}`
- `eval/repair_dataset.yaml` — 50 hand-authored broken-LaTeX entries
- `eval/anchor_match.py` — `flatten_kinds(latex)`, `anchor_present(output, anchor)`
- `eval/golden_lib.py` — `load_golden_set()`, `load_recordings()`, `RecordedPlanner`
- `eval/record_planner_turns.py` — live recorder → `eval/recordings/<id>.json`
- `eval/run_real_baseline.py` — `--mode recorded|live` → `eval/reports/<date>-baseline.md`
- `eval/known-gaps.md` — anchor-match failure triage table
- `tests/conftest.py` — puts `eval/` on `sys.path` for tests
- `tests/test_golden_set_gen.py`, `tests/test_anchor_match.py`, `tests/test_golden_set.py`, `tests/test_repair_dataset.py`

Modified: `pyproject.toml` (eval extra), `.github/workflows/audit.yml` (eval extra in uv lines), `README.md` + `docs/comparison.md` (labeled baseline numbers), `CHANGELOG.md` (Unreleased entry).

Responsibilities: `eval/` holds all measurement tooling (never imported by `src/`); `tests/` holds the pytest suites; `tests/conftest.py` is the only seam that exposes `eval/` modules to tests.

---

### Task 1: Golden set fixture generator

**Files:**
- Create: `eval/generate_golden_set.py`
- Create: `eval/golden_set.yaml` (generated, committed)
- Test: `tests/test_golden_set_gen.py`

**Interfaces:**
- Consumes: `docs/test-prompts-100.md` (markdown tables, 8 sections `## A.`–`## H.`, columns: ID / 测试输入 / 预期关键结构)
- Produces: `parse_prompts(md_path: Path) -> list[dict]` returning `{"id": str, "category": str, "input": str, "anchor": str}`; CLI writes `{"entries": [...]}` to `eval/golden_set.yaml`

- [ ] **Step 0: Add the `eval` extra so all later commands work**

In `pyproject.toml` `[project.optional-dependencies]`, after the `cas-eval` block, add:

```toml
eval = [
    "pyyaml>=6.0.2,<7",
]
```

Run: `uv lock`
Expected: lockfile updated without error.

- [ ] **Step 1: Write the failing test**

Create `tests/test_golden_set_gen.py`:

```python
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def test_generated_fixture_has_100_unique_entries():
    data = yaml.safe_load((REPO / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))
    entries = data["entries"]
    assert len(entries) == 100
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == 100


def test_every_entry_has_input_and_anchor():
    data = yaml.safe_load((REPO / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))
    for e in data["entries"]:
        assert e["input"].strip()
        assert e["anchor"].strip()


def test_all_eight_categories_present():
    data = yaml.safe_load((REPO / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))
    assert len({e["category"] for e in data["entries"]}) == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra eval pytest tests/test_golden_set_gen.py -v`
Expected: FAIL — `eval/golden_set.yaml` does not exist.

- [ ] **Step 3: Write the generator**

Create `eval/generate_golden_set.py`:
- Parse `docs/test-prompts-100.md`: track the current `## X. ...（001–012）` heading as `category`; for each table row starting with `| 0`, split cells: id (int-like string), input, anchor. Strip markdown emphasis from cells. Skip non-table lines.
- `parse_prompts(md_path)` returns the list above.
- `main()`: parse, validate count == 100 and unique ids, write `eval/golden_set.yaml` with `{"entries": [...]}` (`allow_unicode=True`, `sort_keys=False`).

- [ ] **Step 4: Generate and run tests**

Run: `uv run python eval/generate_golden_set.py`
Run: `uv run --extra dev --extra eval pytest tests/test_golden_set_gen.py -v`
Expected: 3 passed.

- [ ] **Step 5: Spot-check and commit**

Run: `uv run --extra dev --extra eval pytest tests/test_golden_set_gen.py -q` and `head -20 eval/golden_set.yaml` — confirm categories A–H each appear (spec §9 requires a human spot-check).
Commit: `eval: generate golden set fixture from 100 manual prompts`

---

### Task 2: Anchor matcher

**Files:**
- Create: `eval/anchor_match.py`
- Create: `tests/conftest.py`
- Test: `tests/test_anchor_match.py`

**Interfaces:**
- Consumes: `texada.semantic.parser.SemanticParser` (`parse(latex) -> SemanticDocument` with `.root: SemanticUnit`, fields `kind`, `value`, `role`, `children`)
- Produces: `flatten_kinds(latex: str) -> list[str]` (pre-order walk of `SemanticUnit.kind`); `anchor_present(output_latex: str, anchor_latex: str) -> bool` (anchor kind list is a subsequence of output kind list)

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
```

Create `tests/test_anchor_match.py`:

```python
from anchor_match import anchor_present, flatten_kinds


def test_equivalent_spellings_pass():
    assert anchor_present(r"\dfrac{a}{b}", r"\frac{a}{b}") is True
    assert anchor_present(r"\left(x+1\right)", r"(x+1)") is True


def test_dropped_operator_detected():
    assert anchor_present(r"x+y", r"x\cdot y") is False


def test_degradation_detected():
    # iiint downgraded to int must fail an iiint anchor
    assert anchor_present(r"\int_{0}^{1} f\,dx", r"\iiint_{0}^{1} f\,dx") is False


def test_subsequence_semantics():
    # anchor kinds must appear in order, not necessarily contiguously
    kinds = flatten_kinds(r"\frac{a}{b}+c")
    assert "fraction" in kinds or "genfrac" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra eval pytest tests/test_anchor_match.py -v`
Expected: FAIL — `ModuleNotFoundError: anchor_match` (conftest exists, module missing).

- [ ] **Step 3: Write the matcher**

Create `eval/anchor_match.py`:

```python
from texada.semantic.parser import SemanticParser

_PARSER = SemanticParser()


def flatten_kinds(latex: str) -> list[str]:
    doc = _PARSER.parse(latex)
    out: list[str] = []

    def walk(unit):
        out.append(unit.kind)
        for child in unit.children:
            walk(child)

    walk(doc.root)
    return out


def _is_subsequence(small: list[str], big: list[str]) -> bool:
    it = iter(big)
    return all(any(s == b for b in it) for s in small)


def anchor_present(output_latex: str, anchor_latex: str) -> bool:
    return _is_subsequence(flatten_kinds(anchor_latex), flatten_kinds(output_latex))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev --extra eval pytest tests/test_anchor_match.py -v`
Expected: 4 passed. If `test_dropped_operator_detected` fails, adjust the anchor fixtures — do **not** weaken the matcher to make tests pass; record the case in `eval/known-gaps.md` instead.

- [ ] **Step 5: Commit**

Commit: `eval: add semantic anchor matcher reusing Semantic Layer`

---

### Task 3: Recorded planner and golden set suite

**Files:**
- Create: `eval/golden_lib.py`
- Create: `eval/recordings/sample-001.json`, `eval/recordings/sample-013.json` (2 hand-authored sample recordings)
- Test: `tests/test_golden_set.py`

**Interfaces:**
- Consumes: `eval/golden_set.yaml`; `texada.agent.protocol.PlannerTurn`, `PlannerToolCall`; `texada.agent.runtime.TeXadaAgentRuntime`; `texada.config.TeXadaConfig`
- Produces:
  - `load_golden_set() -> list[dict]` (reads `eval/golden_set.yaml` relative to repo root)
  - `load_recordings() -> dict[str, dict]` (reads `eval/recordings/*.json`, keyed by `input`)
  - `RecordedPlanner(turns: list[dict])` — implements `plan(messages, tools) -> PlannerTurn` (pops turns in order, reconstructing `PlannerTurn(tool_calls=[PlannerToolCall(id=..., name=..., arguments=...)])`), `generate_latex(...) -> str` (returns the recording's `final_latex`), `extract_latex(content) -> str` (strip)
- Recording JSON schema: `{"input": str, "turns": [{"tool_calls": [{"id": str, "name": str, "arguments": dict}]}], "final_latex": str}`

- [ ] **Step 1: Write the two sample recordings by hand**

Create `eval/recordings/sample-001.json` (input `x 加上 y`, single turn calling `compile_tex` with `{"latex": "x+y"}` then a final turn with no tool calls and `final_latex: "x+y"` — follow the real planner protocol: a turn with `tool_calls: []` ends the loop; check `tests/test_agent_runtime.py` for the exact terminating-turn shape before writing). Create `eval/recordings/sample-013.json` (input `a 除以 b 的分数`, `\frac{a}{b}`).

- [ ] **Step 2: Write the failing test**

Create `tests/test_golden_set.py`:

```python
import pytest
from unittest.mock import AsyncMock
```

(conftest puts `eval/` on `sys.path`, so eval modules are imported by bare name)

```python
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from golden_lib import RecordedPlanner, load_golden_set, load_recordings

RECORDINGS = load_recordings()
GOLDEN = {e["input"]: e for e in load_golden_set()}
RECORDED_INPUTS = [text for text in RECORDINGS if text in GOLDEN]


@pytest.mark.parametrize("text", RECORDED_INPUTS)
async def test_recorded_case_passes_all_layers(tmp_path, text):
    rec = RECORDINGS[text]
    entry = GOLDEN[text]
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=RecordedPlanner(rec["turns"]),
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run(text)

    from anchor_match import anchor_present
    assert result.latex.strip(), "empty result"
    assert anchor_present(result.latex, entry["anchor"]), f"anchor missing in {result.latex}"
    assert result.valid, "compile failed"
    assert result.render.katex_html, "render failed"
    assert result.trace, "trace not expandable"


async def test_missing_recording_is_skipped_not_passed(tmp_path):
    # a golden entry without a recording must not silently pass
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=None)
    assert runtime is not None  # placeholder guard; real skip behavior asserted via RECORDED_INPUTS filter
```

Delete the placeholder second test in Step 4 once the filter logic is verified (it exists only to force the implementer to think about the skip rule).

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev --extra eval pytest tests/test_golden_set.py -v`
Expected: FAIL — `golden_lib` does not exist.

- [ ] **Step 4: Write golden_lib**

Create `eval/golden_lib.py` with `load_golden_set`, `load_recordings`, `RecordedPlanner` per the Interfaces block. Remove the placeholder second test; instead assert the skip rule directly: entries in `load_golden_set()` without recordings are excluded from `RECORDED_INPUTS` (assert `set(RECORDED_INPUTS) <= set(GOLDEN)`).

Run: `uv run --extra dev --extra eval pytest tests/test_golden_set.py -v`
Expected: 2 passed (2 sample recordings). If a layer fails, triage per spec §6: real defect → bug list; equivalent spelling → equivalent table; matcher too strict → `eval/known-gaps.md`.

- [ ] **Step 5: Add the run_id wiring test**

Append to `tests/test_golden_set.py`:

```python
async def test_agent_endpoint_writes_run_log_with_trace(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from texada import api
    from texada.config import TeXadaConfig
    from texada.store.run_log import RunLogStore

    config = TeXadaConfig(data_dir=tmp_path)

    def factory(cfg, *, model=None, backend=None):
        runtime = TeXadaAgentRuntime(cfg, model=RecordedPlanner(RECORDINGS["x 加上 y"]["turns"]))
        runtime.backend.ensure_ready = AsyncMock(return_value=True)
        return runtime

    monkeypatch.setattr(api, "TeXadaAgentRuntime", factory)
    with TestClient(api.create_app(config)) as client:
        resp = client.post("/api/agent", json={"text": "x 加上 y"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id
    entry = await RunLogStore(config).get(run_id)
    assert entry is not None
    assert entry.trace_json
```

Run: `uv run --extra dev --extra eval pytest tests/test_golden_set.py -v`
Expected: 3 passed. If the aiosqlite cross-loop read is flaky, fall back to asserting `resp.json()["trace"]` is non-empty and `run_id` non-empty, and record the limitation in `eval/known-gaps.md`.

- [ ] **Step 6: Commit**

Commit: `eval: add recorded-mode golden set with four assertion layers`

---

### Task 4: Repair dataset

**Files:**
- Create: `eval/repair_dataset.yaml` (50 entries)
- Test: `tests/test_repair_dataset.py`

**Interfaces:**
- Consumes: `texada.tools.registry.TeXToolset` (sync methods `repair_tex(latex) -> dict` with `"latex"`, `compile_tex(latex) -> dict` with `"valid"`, `render_math(latex) -> dict`)
- Produces: `eval/repair_dataset.yaml` schema `{entries: [{id, broken, note}]}`; deterministic test

- [ ] **Step 1: Write the failing test**

Create `tests/test_repair_dataset.py`:

```python
import yaml
from pathlib import Path

from texada.config import TeXadaConfig
from texada.tools.registry import TeXToolset

DATA = yaml.safe_load((Path(__file__).resolve().parents[1] / "eval" / "repair_dataset.yaml").read_text(encoding="utf-8"))["entries"]


def test_dataset_has_50_entries():
    assert len(DATA) == 50


async def test_all_broken_latex_repairs_to_valid_renderable(tmp_path):
    toolset = TeXToolset(TeXadaConfig(data_dir=tmp_path))
    for e in DATA:
        repaired = toolset.repair_tex(e["broken"])["latex"]
        assert toolset.compile_tex(repaired)["valid"], f"{e['id']}: not valid after repair: {repaired}"
        toolset.render_math(repaired)  # raises ValueError if invalid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra eval pytest tests/test_repair_dataset.py -v`
Expected: FAIL — dataset missing.

- [ ] **Step 3: Author the dataset**

Create `eval/repair_dataset.yaml` with 50 entries. Required coverage: missing closing groups in `\frac`/`\sqrt`; dropped `\sum`/`\int` limits; `\iiint`→`\int` degradation; unmatched `\left`; stray `$` delimiters; empty `{}` arguments; double `\\` in matrices. Each `broken` value must be genuinely broken (verify: `compile_tex(broken)["valid"] is False` before adding it).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev --extra eval pytest tests/test_repair_dataset.py -v`
Expected: 2 passed. Any entry that fails repair → either fix the dataset entry (if it was a bad case) or file a real defect; never delete failing entries silently.

- [ ] **Step 5: Commit**

Commit: `eval: add 50-entry deterministic repair dataset`

---

### Task 5: Recorder and baseline runner

**Files:**
- Create: `eval/record_planner_turns.py`
- Create: `eval/run_real_baseline.py`

**Interfaces:**
- Consumes: `golden_lib.load_golden_set()`, `anchor_match.anchor_present`; `texada.core.model.MiniCPMModel` (via `TeXadaConfig` defaults); `RecordedPlanner`
- Produces:
  - `RecordingPlanner(inner, sink: dict)` wrapping a real planner, recording `plan()` call arguments per entry; `record_planner_turns.py --out eval/recordings` writes `<input-slug>.json` per entry (schema in Task 3)
  - `run_real_baseline.py --mode recorded|live [--report eval/reports/<date>-baseline.md]`: recorded mode replays recordings through the pipeline (same assertions as CI); live mode runs the real local model. Report contains: mode, model name, date, per-layer pass/fail counts, structural pass rate, p50/p95 latency (live only), scope disclaimer.

- [ ] **Step 1: Write the recorder**

Create `eval/record_planner_turns.py`: for each golden entry, construct `RecordingPlanner(MiniCPMModel(config))`, run `TeXadaAgentRuntime(config, model=recorder).run(entry["input"])`, write `{"input", "turns", "final_latex"}` JSON. Requires a reachable local model; the script prints a clear error and exits non-zero when the backend is unreachable.

- [ ] **Step 2: Write the baseline runner with an offline mode**

Create `eval/run_real_baseline.py`. `--mode recorded`: for each entry with a recording, construct runtime with `RecordedPlanner`, mock backend readiness, run, evaluate the four layers, aggregate counts, write the report. `--mode live`: same but with the real model and latency measurement. Report template includes the mandatory disclaimer line: "Development-regression scope; not a general benchmark."

- [ ] **Step 3: Verify the recorded mode end-to-end (no model needed)**

Run: `uv run --extra dev --extra eval python eval/run_real_baseline.py --mode recorded`
Expected: report written to `eval/reports/2026-09-19-baseline.md` (use today's date), counts shown, disclaimer present.

- [ ] **Step 4: Verify the live-mode entry point fails cleanly without a model**

Run: `uv run --extra dev --extra eval python eval/run_real_baseline.py --mode live`
Expected: clear "backend unreachable" message, non-zero exit, no partial report file. (If a local model IS reachable, run the real baseline now and keep the report — spec gate 2 uses those numbers.)

- [ ] **Step 5: Commit**

Commit: `eval: add planner-turn recorder and baseline runner`

---

### Task 6: Known-gaps, first report, README and comparison numbers

**Files:**
- Create: `eval/known-gaps.md`
- Create: `eval/reports/2026-09-19-baseline.md` (from Task 5 Step 3, or the live run)
- Modify: `README.md` — add a short "Local evaluation" subsection near the existing latency measurement
- Modify: `docs/comparison.md` — add one evidence line citing the baseline
- Modify: `CHANGELOG.md` — Unreleased entry (EN + 中文)

**Interfaces:**
- Consumes: the report from Task 5
- Produces: labeled numbers in README and comparison.md; triage table header in known-gaps.md

- [ ] **Step 1: Create the triage file**

Create `eval/known-gaps.md` with a table header: `| ID | Anchor | Output | Layer | Verdict (defect / equivalent-spelling / matcher-strict) | Action |`. Populate rows from any failures seen in Tasks 2-4.

- [ ] **Step 2: Write README numbers**

In `README.md` (both language sections if the section is bilingual), add under a "Local evaluation" heading: structural pass rate and repair pass rate from the report, each followed by: "development-regression scope, not a general benchmark" and the report path. If only recorded-mode numbers exist, label them "recorded-mode (pipeline gate)" and add: "live-model numbers pending — run `eval/run_real_baseline.py --mode live`".

- [ ] **Step 3: Add the comparison line**

In `docs/comparison.md`, after the existing "not a benchmark" declaration, add one line citing the baseline report path and the two numbers with the same scope label. Do not change any existing wording in that file.

- [ ] **Step 4: Changelog**

Add to CHANGELOG.md Unreleased (EN + 中文): golden set (100 entries, four assertion layers), repair dataset (50 entries), `eval` extra, baseline report; note zero runtime behavior change.

- [ ] **Step 5: Full-suite check and commit**

Run: `uv run --extra dev --extra eval pytest -q`
Expected: all previous tests plus the new suites pass.
Run: `uv run --extra dev --extra eval ruff check .`
Commit: `docs: publish first baseline numbers and known-gaps triage`

---

### Task 7: CI wiring

**Files:**
- Modify: `.github/workflows/audit.yml` (add `--extra eval` to the three uv lines)
- Modify: `pyproject.toml` (already edited in Task 1 Step 0 — verify)

- [ ] **Step 1: Add the eval extra to CI uv commands**

In `.github/workflows/audit.yml`, change `uv run --extra dev --extra cas-eval ruff check .` → `uv run --extra dev --extra cas-eval --extra eval ruff check .`; same for the Pytest step and the `uv export` line. Do not add any live-model job to CI (ADR-013: real mode never gates CI).

- [ ] **Step 2: Verify locally what CI will run**

Run: `uv run --extra dev --extra cas-eval --extra eval pytest -q` and `uv run --extra dev --extra cas-eval --extra eval ruff check .`
Expected: green, same as Task 6 Step 5.

- [ ] **Step 3: Commit**

Commit: `ci: include eval extra in audit workflow`

---

## Definition of Done (spec §8 gates)

1. `uv run --extra dev --extra cas-eval --extra eval pytest` green with the four new suites.
2. `eval/reports/<date>-baseline.md` exists with both numbers, scope disclaimer, and README/comparison citations.
3. `git diff main -- src/` shows no runtime behavior change.
4. `eval/known-gaps.md` exists; zero silently-swallowed anchor failures.
