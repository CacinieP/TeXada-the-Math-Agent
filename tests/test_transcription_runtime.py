"""Source constraints survive candidate routing and revision changes."""

import time
from unittest.mock import AsyncMock, Mock

import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.candidates import DeterministicCandidate
from texada.core.transcription import recognize_transcription
from texada.runtime import CommitBarrierError, FormulaState
from texada.types import RenderMode


def runtime_without_model(tmp_path):
    model = Mock()
    model.plan = AsyncMock(side_effect=AssertionError("unexpected model planning"))
    model.generate_latex = AsyncMock(side_effect=AssertionError("unexpected model inference"))
    backend = Mock()
    backend.ensure_ready = AsyncMock(side_effect=AssertionError("unexpected model startup"))
    return TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=model, backend=backend)


@pytest.mark.parametrize("text", [
    "写一个求和公式，对bn求和",
    "对F(x)进行求和，其中x取遍整数中的元素",
    "写一个求和公式，其中每一项是函数Fi在omega_i上的积分",
])
@pytest.mark.asyncio
async def test_supported_sources_bind_matching_constraints_to_commit(tmp_path, text):
    result = await runtime_without_model(tmp_path).run(text)
    assert result.valid and result.committed and result.tokens_used == 0
    assert result.trace[0]["preprocessed_input"] == text
    check = result.trace[-1]["transcription_constraints"][-1]
    assert check["verdict"] == "MATCH"
    assert check["revision"] == result.revision
    assert check["source_input"] == text
    evidence = next(item for item in result.formula_ledger["evidence"]
                    if item["kind"] == "transcription_constraints")
    assert evidence["sequence"] in result.formula_ledger["commits"][0]["evidence"]


@pytest.mark.parametrize("text, wrong", [
    ("写一个求和公式，对bn求和", r"\sum_{n=1}^{\infty} b_n \sum_{k=1}^{\infty} a_k"),
    ("对F(x)进行求和，其中x取遍整数中的元素", r"\sum_{x=1}^{n} F(x)"),
    ("写一个求和公式，其中每一项是函数Fi在omega_i上的积分",
     r"\sum_{i=1}^n \int_{\omega_i}^{omega_{i+1}} Fi(x)\,dx"),
])
@pytest.mark.asyncio
async def test_compilable_release_failures_cannot_cross_constraint_barrier(tmp_path, text, wrong):
    runtime = runtime_without_model(tmp_path)
    result = await runtime._run_deterministic_candidate(
        DeterministicCandidate(latex=wrong, rule="regression_counterexample"),
        preprocessed=text, render_mode=RenderMode.KATEX, start=time.monotonic(), task="nl",
        transcription_spec=recognize_transcription(text), source_input=text,
    )
    assert result.valid and not result.committed
    assert result.latex == wrong
    assert result.stop_reason == "transcription_constraint_failed"
    assert result.trace[-1]["transcription_constraints"][-1]["verdict"] == "DIFFERENT"
    assert not result.formula_ledger["commits"]


def test_source_constraints_require_fresh_evidence_after_revision():
    state = FormulaState("x")
    state.add_evidence(
        revision=1, kind="transcription_constraints", ok=True, output={"verdict": "MATCH"},
    )
    state.revise("y", expected_revision=1, origin="candidate")
    state.add_evidence(revision=2, kind="compile_tex", ok=True, output={"valid": True})
    state.add_evidence(revision=2, kind="render_math", ok=True)
    with pytest.raises(CommitBarrierError, match="transcription constraint"):
        state.commit(expected_revision=2)
    state.add_evidence(
        revision=2, kind="transcription_constraints", ok=False, output={"verdict": "DIFFERENT"},
    )
    with pytest.raises(CommitBarrierError, match="transcription constraint"):
        state.commit(expected_revision=2)
    evidence = state.add_evidence(
        revision=2, kind="transcription_constraints", ok=True, output={"verdict": "MATCH"},
    )
    assert evidence.sequence in state.commit(expected_revision=2).evidence


def test_revised_candidate_is_rechecked_against_original_source(tmp_path):
    runtime = runtime_without_model(tmp_path)
    text = "写一个求和公式，对bn求和"
    spec = recognize_transcription(text)
    state = runtime._scoped_state(
        spec.latex, origin="candidate", task="nl", transcription_spec=spec, source_input=text,
    )
    runtime._adopt_formula(state, r"\sum_n a_n", origin="candidate")
    checks = runtime._scope_trace([{}], state)[-1]["transcription_constraints"]
    assert [(check["revision"], check["verdict"]) for check in checks] == [
        (1, "MATCH"), (2, "DIFFERENT"),
    ]


@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.asyncio
async def test_supplemental_context_reaches_model_without_old_shortcuts(tmp_path, candidate_first):
    text = "写一个求和公式，对bn求和"
    context = "求和范围是 n 从 2 到 m"
    expected = r"\sum_{n=2}^{m} b_n"
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
    runtime.candidate_engine.propose = Mock(side_effect=AssertionError("context was ignored"))
    result = await runtime.run(text, context=context)
    assert result.valid and result.committed and result.latex == expected
    assert context in str(model.plan.call_args_list[0])
    if candidate_first:
        assert context in model.generate_latex.call_args.args[0]
    assert result.trace[-1]["transcription_recognition"][-1]["reason"] == (
        "transcription_context_requires_planning"
    )
    assert "transcription_constraints" not in result.trace[-1]
