"""Source-faithful sum requests use the normal Agent and backup surfaces."""

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
        raise AssertionError("Recognized transcription requested a model backend")

    monkeypatch.setattr(BackendManager, "ensure_ready", unexpected_model)
    monkeypatch.setattr(MiniCPMModel, "generate_latex", unexpected_model)
    monkeypatch.setattr(MiniCPMModel, "plan", unexpected_model)
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        yield client


@pytest.mark.parametrize(("text", "latex"), [
    ("写一个求和公式，对bn求和", r"\sum_{n} b_n"),
    ("对F(x)进行求和，其中x取遍整数中的元素", r"\sum_{x \in \mathbb{Z}} F(x)"),
    ("对F(x)进行求和，其中x取遍A中的元素", r"\sum_{x \in A} F(x)"),
    ("写一个求和公式，其中每一项是函数Fi在omega_i上的积分",
     r"\sum_{i} \int_{\omega_i} F_i"),
])
def test_sum_api_records_source_and_revision_bound_check(offline_client, text, latex):
    response = offline_client.post("/api/agent", json={"text": text})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert result["committed"] is True
    assert result["latex"] == latex
    assert result["tokens_used"] == 0
    checks = [check for step in result["agent_trace"]
              for check in step.get("transcription_constraints", [])]
    assert checks[-1]["verdict"] == "MATCH"
    assert checks[-1]["revision"] == result["revision"]
    assert result["agent_trace"][0]["preprocessed_input"] == text

    run = offline_client.get(f"/api/runs/{result['run_id']}").json()
    assert run["operation"] == "agent"
    assert run["input_type"] == "nl"
    assert run["input_text"] == text
    assert run["output_latex"] == latex
    assert run["trace"] == result["agent_trace"]
    assert run["inference_fingerprint"]["capture_status"] == "COMPLETE"
    history = offline_client.get("/api/history").json()
    assert len(history) == 1
    assert history[0]["run_id"] == result["run_id"]
    assert history[0]["input_text"] == text


def test_incomplete_region_is_logged_for_clarification_without_history(offline_client):
    text = "写一个求和公式，其中每一项是函数Fi在omega_上的积分"
    response = offline_client.post("/api/agent", json={"text": text})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is False
    assert result["committed"] is False
    assert result["latex"] == ""
    assert result["stop_reason"] == "source_clarification_required"
    assert result["tokens_used"] == 0
    trace = json.dumps(result["agent_trace"], ensure_ascii=False)
    assert text in trace
    assert "clarification" in trace
    assert "下标" in trace
    run = offline_client.get(f"/api/runs/{result['run_id']}").json()
    assert run["input_text"] == text
    assert run["stop_reason"] == "source_clarification_required"
    assert run["trace"] == result["agent_trace"]
    assert offline_client.get("/api/history").json() == []


def test_transcription_evidence_survives_backup_and_replay(offline_client):
    text = "写一个求和公式，其中每一项是函数Fi在omega_i上的积分"
    first = offline_client.post("/api/agent", json={"text": text}).json()
    assert first["committed"] is True
    backup = offline_client.get("/api/export").json()
    assert len(backup["history"]) == len(backup["run_logs"]) == 1
    response = offline_client.post("/api/import", json={
        "mode": "replace", "history": backup["history"], "run_logs": backup["run_logs"],
    })
    assert response.status_code == 200
    restored = offline_client.get(f"/api/runs/{first['run_id']}").json()
    assert restored["trace"] == first["agent_trace"]
    entry = offline_client.get("/api/history").json()[0]
    replay = offline_client.post("/api/agent", json={"text": entry["input_text"]}).json()
    assert replay["committed"] is True
    assert replay["tokens_used"] == 0
    assert replay["latex"] == first["latex"]
    assert replay["agent_trace"][-1]["transcription_constraints"][-1]["verdict"] == "MATCH"
