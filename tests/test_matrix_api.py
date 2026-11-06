"""Matrix presets use the Agent response, history, and request ledger."""
import json

import pytest
from fastapi.testclient import TestClient

from texada.agent.runtime import AgentRunResult, TeXadaAgentRuntime
from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.model import MiniCPMModel
from texada.render.engine import RenderEngine
from texada.types import RenderMode


def test_matrix_api_generates_without_model_and_records_bound_checks(tmp_path, monkeypatch):
    async def unexpected_model(*args, **kwargs):
        raise AssertionError("Matrix presets must use deterministic generation")

    monkeypatch.setattr(BackendManager, "ensure_ready", unexpected_model)
    monkeypatch.setattr(MiniCPMModel, "generate_latex", unexpected_model)
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        response = client.post("/api/matrix", json={
            "spec": {"kind": "tridiagonal", "rows": 10, "columns": 10},
            "render_mode": "latex",
        })
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is True
        assert result["committed"] is True
        assert result["tokens_used"] == 0
        assert "a_{10}" in result["latex"]
        assert "b_{9}" in result["latex"]
        assert "c_{9}" in result["latex"]
        checks = [check for step in result["agent_trace"]
                  for check in step.get("matrix_constraints", [])]
        assert checks[-1]["verdict"] == "MATCH"
        assert checks[-1]["revision"] == result["revision"]

        run = client.get(f"/api/runs/{result['run_id']}").json()
        assert run["operation"] == "agent"
        assert run["tokens_used"] == 0
        assert run["trace"] == result["agent_trace"]
        assert run["inference_fingerprint"]["capture_status"] == "COMPLETE"
        assert run["input_text"].startswith("矩阵预设 ")
        source = json.loads(run["input_text"].removeprefix("矩阵预设 "))
        assert source["kind"] == "tridiagonal"
        assert source["rows"] == source["columns"] == 10
        history = client.get("/api/history").json()
        assert any(item["run_id"] == result["run_id"] for item in history)


@pytest.mark.parametrize("spec", [
    {"rows": 0}, {"rows": True}, {"rows": 1.5}, {"rows": "10"},
    {"rows": 21}, {"columns": "n+1"}, {"index_start": False},
    {"kind": "identity"}, {"element": r"\input{secret}"},
    {"kind": "tridiagonal", "rows": 2, "columns": 3},
])
def test_matrix_api_rejects_invalid_parameters_before_runtime(tmp_path, monkeypatch, spec):
    async def unexpected_runtime(*args, **kwargs):
        raise AssertionError("Invalid matrix parameters reached the runtime")

    monkeypatch.setattr(TeXadaAgentRuntime, "run", unexpected_runtime)
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        response = client.post("/api/matrix", json={"spec": spec})
        assert response.status_code == 422


def test_matrix_api_shares_uncommitted_result_and_logging_contract(tmp_path, monkeypatch):
    config = TeXadaConfig(data_dir=tmp_path)
    captured = {}

    async def rejected_candidate(self, user_input, **kwargs):
        captured.update(kwargs)
        return AgentRunResult(
            latex="x", valid=True,
            render=RenderEngine(config).render("x", mode_override=RenderMode.KATEX),
            semantic_document={"latex": "x"},
            stop_reason="matrix_constraint_failed", committed=False, revision=1,
            trace=[{"step": 1, "matrix_constraints": [{"verdict": "DIFFERENT", "revision": 1}]}],
        )

    monkeypatch.setattr(TeXadaAgentRuntime, "run", rejected_candidate)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/matrix", json={"spec": {"rows": "m", "columns": "n"}})
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is True
        assert result["committed"] is False
        assert result["stop_reason"] == "matrix_constraint_failed"
        assert captured["_matrix_spec"].display == "compact"
        run = client.get(f"/api/runs/{result['run_id']}").json()
        assert run["stop_reason"] == "matrix_constraint_failed"
        assert client.get("/api/history").json() == []


def test_matrix_api_uses_origin_policy(tmp_path):
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        response = client.post(
            "/api/matrix", json={"spec": {}},
            headers={"Origin": "https://example.invalid"},
        )
        assert response.status_code == 403
