"""Recorded-mode golden set: four assertion layers per recorded case.

Only entries that have a committed recording are exercised; a golden entry
without a recording is excluded (never silently passed). The run_id wiring
test proves the API -> run log store observability chain once.
"""
from unittest.mock import AsyncMock

import pytest
from anchor_match import anchor_present
from golden_lib import RecordedPlanner, anchor_variants, load_golden_set, load_recordings

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig

RECORDINGS = load_recordings()
GOLDEN = {e["input"]: e for e in load_golden_set()}
RECORDED_INPUTS = [text for text in RECORDINGS if text in GOLDEN]


def test_recorded_inputs_are_a_subset_of_the_golden_set():
    assert set(RECORDED_INPUTS) <= set(GOLDEN)


def test_recorded_inputs_are_not_vacuously_empty():
    # Guards against a silently empty suite if recordings are lost.
    assert RECORDED_INPUTS, "no recordings matched golden set inputs"


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

    assert result.latex.strip(), "empty result"
    variants = anchor_variants(entry["anchor"])
    if variants:
        assert any(
            anchor_present(result.latex, v) for v in variants
        ), f"anchor missing in {result.latex!r} (anchor {entry['anchor']!r})"
    assert result.valid, "compile failed"
    assert result.render.katex_html, "render failed"
    assert result.trace, "trace not expandable"


async def test_agent_endpoint_writes_run_log_with_trace(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from texada import api
    from texada.config import TeXadaConfig
    from texada.store.run_log import RunLogStore

    config = TeXadaConfig(data_dir=tmp_path)
    text = RECORDED_INPUTS[0]

    def factory(cfg, *, model=None, backend=None):
        runtime = TeXadaAgentRuntime(
            cfg, model=RecordedPlanner(RECORDINGS[text]["turns"])
        )
        runtime.backend.ensure_ready = AsyncMock(return_value=True)
        return runtime

    monkeypatch.setattr(api, "TeXadaAgentRuntime", factory)
    with TestClient(api.create_app(config)) as client:
        resp = client.post("/api/agent", json={"text": text})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"]
    entry = await RunLogStore(config).get(body["run_id"])
    assert entry is not None, "run_id not written to run log store"
    assert entry.trace_available, "trace not persisted in run log"
    assert entry.trace, "trace not persisted in run log"
