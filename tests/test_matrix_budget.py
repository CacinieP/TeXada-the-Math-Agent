"""Large supported matrix formulas pass tools, validation, and backup roundtrips."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.semantic.structure import MAX_EXPRESSION_CHARS
from texada.tools import TeXToolset


@pytest.mark.parametrize("spec", [
    {"rows": 19, "columns": 19},
    {"rows": 20, "columns": 20},
    {"rows": 20, "columns": 20, "element": r"\varepsilon"},
    {"kind": "tridiagonal", "rows": 20, "columns": 20,
     "diagonal": "1" * 64, "upper": "2" * 64, "lower": "3" * 64},
])
def test_large_matrix_complete_api_and_portability_flow(tmp_path, monkeypatch, spec):
    monkeypatch.setattr(
        BackendManager, "ensure_ready",
        AsyncMock(side_effect=AssertionError("matrix called a model backend")),
    )
    config = TeXadaConfig(data_dir=tmp_path)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/matrix", json={"spec": spec})
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] and result["committed"]
        assert result["tokens_used"] == 0
        latex = result["latex"]
        assert 4000 < len(latex) <= MAX_EXPRESSION_CHARS
        checked = client.post("/api/validate", json={"latex": latex})
        assert checked.status_code == 200
        assert checked.json()["valid"]

        history = client.get("/api/history/export").json()
        history_import = client.post("/api/history/import", json=history)
        assert history_import.status_code == 200
        runs = client.get("/api/runs/export").json()
        assert any(len(entry["input_text"]) > 4000 for entry in runs["run_logs"])
        runs_import = client.post("/api/runs/import", json=runs)
        assert runs_import.status_code == 200

        backup = client.get("/api/export").json()
        restored = client.post("/api/import", json={**backup, "mode": "replace"})
        assert restored.status_code == 200
        assert client.get("/api/history").json()[0]["latex"] == latex
        assert client.get(f"/api/runs/{result['run_id']}").json()["output_latex"] == latex


@pytest.mark.parametrize("value", [0, -1, True, MAX_EXPRESSION_CHARS + 1])
def test_configurable_tool_budget_stays_bounded(tmp_path, value):
    with pytest.raises(ValueError, match="max_tex_length"):
        TeXToolset(TeXadaConfig(data_dir=tmp_path), max_tex_length=value)


def test_formula_api_limits_are_bounded(tmp_path):
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))) as client:
        latex = "x" * (MAX_EXPRESSION_CHARS + 1)
        assert client.post("/api/validate", json={"latex": latex}).status_code == 422
        assert client.post("/api/history/import", json={"history": [{
            "input_text": "matrix", "latex": latex,
        }]}).status_code == 422
        assert client.post("/api/runs/import", json={"run_logs": [{
            "run_id": "oversized-matrix", "output_latex": latex,
        }]}).status_code == 422
