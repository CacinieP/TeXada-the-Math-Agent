"""Matrix candidate routing and revision-bound constraint regression tests."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.candidates import DeterministicCandidate
from texada.core.matrices import MatrixSpec, generate_matrix
from texada.runtime import CommitBarrierError, FormulaState


def matrix_runtime(tmp_path):
    model = Mock()
    model.plan = AsyncMock(side_effect=AssertionError("matrix requested model planning"))
    model.generate_latex = AsyncMock(side_effect=AssertionError("matrix requested inference"))
    backend = Mock()
    backend.ensure_ready = AsyncMock(side_effect=AssertionError("matrix started a model backend"))
    return TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path), model=model, backend=backend,
    )


@pytest.mark.parametrize("order", [None, 10])
@pytest.mark.asyncio
async def test_original_matrix_requests_use_checked_zero_model_candidates(tmp_path, order):
    runtime = matrix_runtime(tmp_path)
    text = "写一个" + ("10阶" if order else "") + "矩阵，主对角线是ai，两条次对角线分别是bi，ci"
    result = await runtime.run(text)

    assert result.valid and result.committed
    assert result.tokens_used == 0
    assert result.trace[0]["candidate_rule"] == "matrix_nl"
    checks = result.trace[-1]["matrix_constraints"]
    assert checks[-1]["verdict"] == "MATCH"
    assert checks[-1]["revision"] == result.revision
    assert "b_" in result.latex and "c_" in result.latex
    assert result.trace[0]["preprocessed_input"] == text
    constraint_evidence = next(
        item for item in result.formula_ledger["evidence"]
        if item["kind"] == "matrix_constraints"
    )
    assert constraint_evidence["sequence"] in result.formula_ledger["commits"][0]["evidence"]


@pytest.mark.asyncio
async def test_structured_preset_and_natural_language_share_generation(tmp_path):
    runtime = matrix_runtime(tmp_path)
    spec = MatrixSpec(kind="tridiagonal", rows=10, columns=10)
    preset = await runtime.run("矩阵预设", _matrix_spec=spec)
    natural = await runtime.run("写一个10阶矩阵，主对角线是ai，两条次对角线分别是bi，ci")
    assert preset.latex == natural.latex == generate_matrix(spec)
    assert preset.committed and natural.committed
    assert preset.trace[0]["candidate_rule"] == "matrix_parameters"


@pytest.mark.asyncio
async def test_compilable_wrong_matrix_is_retained_but_cannot_commit(tmp_path, monkeypatch):
    runtime = matrix_runtime(tmp_path)
    wrong = r"\begin{pmatrix}a & b \\ c & d\end{pmatrix}"
    monkeypatch.setattr("texada.agent.runtime.generate_matrix", lambda spec: wrong)
    result = await runtime.run("矩阵预设", _matrix_spec=MatrixSpec(kind="tridiagonal"))

    assert result.valid
    assert not result.committed
    assert result.latex == wrong
    assert result.stop_reason == "matrix_constraint_failed"
    assert result.trace[-1]["matrix_constraints"][-1]["verdict"] == "DIFFERENT"
    assert not result.formula_ledger["commits"]


@pytest.mark.asyncio
async def test_unsupported_matrix_presentation_cannot_claim_a_match(tmp_path, monkeypatch):
    runtime = matrix_runtime(tmp_path)
    monkeypatch.setattr(
        "texada.agent.runtime.generate_matrix", lambda spec: r"\phantom{x}",
    )
    result = await runtime.run("矩阵预设", _matrix_spec=MatrixSpec())
    assert result.valid
    assert not result.committed
    assert result.trace[-1]["matrix_constraints"][-1]["verdict"] == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_matrix_requests_have_independent_state_when_concurrent(tmp_path):
    runtime = matrix_runtime(tmp_path)
    specs = [MatrixSpec(rows=2, columns=3), MatrixSpec(kind="tridiagonal", rows=10, columns=10)]
    results = await asyncio.gather(*(
        runtime.run("矩阵预设", _matrix_spec=spec) for spec in specs
    ))
    for spec, result in zip(specs, results, strict=True):
        assert result.committed
        assert result.latex == generate_matrix(spec)
        assert result.trace[-1]["matrix_constraints"][-1]["spec"] == spec.model_dump()


def test_matrix_constraint_evidence_cannot_be_reused_after_revision():
    state = FormulaState("x")
    state.add_evidence(
        revision=1, kind="matrix_constraints", ok=True, output={"verdict": "MATCH"},
    )
    state.revise("y", expected_revision=1, origin="candidate")
    state.add_evidence(revision=2, kind="compile_tex", ok=True, output={"valid": True})
    state.add_evidence(revision=2, kind="render_math", ok=True)
    with pytest.raises(CommitBarrierError, match="matrix constraint"):
        state.commit(expected_revision=2)
    state.add_evidence(
        revision=2, kind="matrix_constraints", ok=False, output={"verdict": "DIFFERENT"},
    )
    with pytest.raises(CommitBarrierError, match="matrix constraint"):
        state.commit(expected_revision=2)
    matched = state.add_evidence(
        revision=2, kind="matrix_constraints", ok=True, output={"verdict": "MATCH"},
    )
    assert matched.sequence in state.commit(expected_revision=2).evidence


def test_unrecognized_matrix_grammar_keeps_its_coverage_explicit(tmp_path):
    runtime = matrix_runtime(tmp_path)
    state = runtime._scoped_state(
        r"\begin{pmatrix}a\end{pmatrix}", origin="candidate", task="nl",
        matrix_requested=True,
    )
    trace = runtime._scope_trace([{}], state)
    assert trace[-1]["matrix_recognition"] == [{
        "verdict": "NOT_CHECKED", "coverage": [],
        "reason": "outside_supported_matrix_grammar", "revision": 1,
    }]


@pytest.mark.asyncio
async def test_matrix_hint_fallback_reports_its_unchecked_request_scope(tmp_path):
    runtime = matrix_runtime(tmp_path)
    runtime.candidate_engine.propose = Mock(return_value=DeterministicCandidate(
        latex=r"\begin{pmatrix}a\end{pmatrix}", rule="explicit_hint",
    ))
    result = await runtime.run("写一个分块矩阵")
    assert result.valid and result.committed
    assert result.trace[-1]["matrix_recognition"][-1]["verdict"] == "NOT_CHECKED"
    assert "matrix_constraints" not in result.trace[-1]


@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.asyncio
async def test_matrix_context_reaches_planning_and_candidate_generation(tmp_path, candidate_first):
    context = "使用方括号，元素写成 x_{i,j}，不要用 a。"
    expected = r"\begin{bmatrix}x_{1,1} & x_{1,2} \\ x_{2,1} & x_{2,2}\end{bmatrix}"
    compile_turn = PlannerTurn(tool_calls=[PlannerToolCall(
        "compile", "compile_tex", {"latex": expected},
    )])
    finish_turn = PlannerTurn(tool_calls=[PlannerToolCall(
        "finish", "finish_formula", {"expected_revision": 1},
    )])
    model = Mock()
    model.generate_latex = AsyncMock(return_value=expected)
    model.plan = AsyncMock(side_effect=[finish_turn] if candidate_first
                           else [compile_turn, finish_turn])
    model.consume_tokens_used = Mock(return_value=0)
    backend = Mock()
    backend.ensure_ready = AsyncMock()
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first),
        model=model, backend=backend,
    )
    # A previous shortcut must not consume this request after matrix recognition falls back.
    runtime.candidate_engine.propose = Mock(side_effect=AssertionError("context was ignored"))
    result = await runtime.run("写一个2阶矩阵", context=context)
    assert result.valid and result.committed
    assert result.latex == expected
    assert context in str(model.plan.call_args_list[0])
    if candidate_first:
        assert context in model.generate_latex.call_args.args[0]
    else:
        model.generate_latex.assert_not_called()
    assert result.trace[-1]["matrix_recognition"][-1]["reason"] == (
        "matrix_context_requires_planning"
    )
    assert "matrix_constraints" not in result.trace[-1]


@pytest.mark.asyncio
async def test_matrix_budget_is_separate_from_default_tool_budget(tmp_path):
    runtime = matrix_runtime(tmp_path)
    spec = MatrixSpec(rows=20, columns=20, element=r"\varepsilon")
    result = await runtime.run("矩阵预设", _matrix_spec=spec)
    assert result.valid and result.committed
    assert len(result.latex) > 4000
    ordinary = await runtime.tools.execute("compile_tex", {"latex": result.latex})
    assert not ordinary.ok
    assert "4000 characters" in ordinary.error
