"""Additional presets use the existing matrix Agent, history and backup contract."""

import json

import pytest
from fastapi.testclient import TestClient

from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.model import MiniCPMModel


@pytest.fixture
def offline_client(tmp_path, monkeypatch):
    async def unexpected_model(*args, **kwargs):
        raise AssertionError("A supported matrix preset requested model inference")

    monkeypatch.setattr(BackendManager, "ensure_ready", unexpected_model)
    monkeypatch.setattr(MiniCPMModel, "generate_latex", unexpected_model)
    monkeypatch.setattr(MiniCPMModel, "plan", unexpected_model)
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        yield client


@pytest.mark.parametrize("kind", [
    "identity", "zero", "diagonal", "upper_triangular", "lower_triangular",
])
def test_new_presets_record_current_matching_evidence_and_replay(offline_client, kind):
    spec = {"kind": kind, "rows": 3, "columns": 2 if kind == "zero" else 3,
            "index_start": 0, "bracket": "bmatrix", "diagonal": "d_i", "element": "x"}
    response = offline_client.post("/api/matrix", json={"spec": spec})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] and result["committed"] and result["tokens_used"] == 0
    checks = result["agent_trace"][-1]["matrix_constraints"]
    assert checks[-1]["verdict"] == "MATCH"
    assert checks[-1]["revision"] == result["revision"]
    assert checks[-1]["spec"]["kind"] == kind
    history = offline_client.get("/api/history").json()
    assert len(history) == 1 and history[0]["input_type"] == "matrix"
    restored_spec = json.loads(history[0]["input_text"].removeprefix("矩阵预设 "))
    assert restored_spec.items() >= spec.items()
    run = offline_client.get(f"/api/runs/{result['run_id']}").json()
    assert run["trace"] == result["agent_trace"]
    assert run["inference_fingerprint"]["calls"] == []
    replay = offline_client.post("/api/matrix", json={"spec": restored_spec}).json()
    assert replay["committed"] and replay["latex"] == result["latex"]


def test_symbolic_triangular_history_survives_backup(offline_client):
    spec = {"kind": "lower_triangular", "rows": "n", "columns": "n",
            "element": "x", "index_start": 0}
    result = offline_client.post("/api/matrix", json={"spec": spec}).json()
    assert result["committed"] and r"_{n\times n}" in result["latex"]
    backup = offline_client.get("/api/export").json()
    imported = offline_client.post("/api/import", json={
        "mode": "replace", "history": backup["history"], "run_logs": backup["run_logs"],
    })
    assert imported.status_code == 200
    entry = offline_client.get("/api/history").json()[0]
    restored_spec = json.loads(entry["input_text"].removeprefix("矩阵预设 "))
    replay = offline_client.post("/api/matrix", json={"spec": restored_spec}).json()
    assert replay["committed"] and replay["latex"] == result["latex"]
    run = offline_client.get(f"/api/runs/{result['run_id']}").json()
    assert run["trace"] == result["agent_trace"]
