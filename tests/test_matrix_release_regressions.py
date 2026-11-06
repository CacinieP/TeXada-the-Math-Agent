"""Offline request-fidelity regressions from the official v0.4.3 replay."""

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.matrices import MatrixSpec, check_matrix, generate_matrix, recognize_matrix
from texada.core.validator import LaTeXValidator

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "eval/matrix_release_regressions.json").read_text(
        encoding="utf-8",
    )
)
CASES = FIXTURE["cases"]


def test_fixture_retains_three_official_release_observations():
    assert FIXTURE["schema_version"] == 1
    assert FIXTURE["provenance"]["release_tag"] == "v0.4.3"
    assert FIXTURE["provenance"]["source_commit"] == (
        "6adcba0ab1540f2efb1bf78156783842001bc72c"
    )
    assert {case["case_id"]: case["replay_run_id"] for case in CASES} == {
        "C10": "1a9965012d7047a893933cb6e4939ee4",
        "C11": "d9f13b145fda403eb72ceecb57c885fc",
        "C12": "92ae2ed601264182a390bc69ca49d33d",
    }
    assert len(CASES) == 3
    assert len({case["lineage_source_run_id"] for case in CASES}) == 3
    assert CASES[1]["observed_latex"] == CASES[2]["observed_latex"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_original_output_compiles_but_fails_request_constraints(case):
    latex = case["observed_latex"]
    assert hashlib.sha256(latex.encode()).hexdigest() == case["observed_latex_sha256"]
    assert case["observed_syntax_valid"] is True
    assert case["observed_committed"] is True
    assert LaTeXValidator().validate(latex).valid

    spec = recognize_matrix(case["input"])
    assert spec == MatrixSpec.model_validate(case["expected_spec"])
    check = check_matrix(spec, latex)
    assert check["verdict"] == "DIFFERENT"
    assert check["diagnostics"]

    corrected = generate_matrix(spec)
    assert LaTeXValidator().validate(corrected).valid
    assert check_matrix(spec, corrected)["verdict"] == "MATCH"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
@pytest.mark.asyncio
async def test_original_output_cannot_cross_current_commit_barrier(tmp_path, monkeypatch, case):
    model = Mock()
    model.plan = AsyncMock(side_effect=AssertionError("unexpected model planning"))
    model.generate_latex = AsyncMock(side_effect=AssertionError("unexpected model inference"))
    backend = Mock()
    backend.ensure_ready = AsyncMock(side_effect=AssertionError("unexpected backend startup"))
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path), model=model, backend=backend,
    )
    monkeypatch.setattr(
        "texada.agent.runtime.generate_matrix", lambda spec: case["observed_latex"],
    )

    result = await runtime.run(case["input"])

    assert result.latex == case["observed_latex"]
    assert result.valid
    assert not result.committed
    assert result.stop_reason == "matrix_constraint_failed"
    check = result.trace[-1]["matrix_constraints"][-1]
    assert check["verdict"] == "DIFFERENT"
    assert check["revision"] == result.revision
    assert not result.formula_ledger["commits"]
    model.plan.assert_not_awaited()
    model.generate_latex.assert_not_awaited()
    backend.ensure_ready.assert_not_awaited()
