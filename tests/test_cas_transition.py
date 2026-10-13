"""Declared transition evidence, algebra corpus and runtime shadow behavior."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from texada.agent.cas_transition import (
    CASTransitionChecker,
    TransitionApplicability,
    TransitionVerdict,
)
from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.cas import AlgebraChecker, CASBasis, CASEvidenceGrade, CASResult, CASStatus
from texada.config import TeXadaConfig
from texada.runtime import FormulaState
from texada.tools import ToolObservation

CORPUS = json.loads(
    (Path(__file__).resolve().parents[1] / "eval/cas_transition_pairs.json").read_text()
)


@pytest.fixture
def checker():
    pytest.importorskip("sympy")
    pytest.importorskip("psutil")
    selected = CASTransitionChecker()
    yield selected
    selected.close()


@pytest.mark.parametrize("case", CORPUS["entries"], ids=lambda case: case["id"])
def test_authored_transition_pairs_reproduce_exact_evidence(checker, case):
    result = checker.check(
        case["before"],
        case["after"],
        parent_revision=3,
        child_revision=4,
        semantics_preserving_declared=True,
        scope_verdict="allowed",
    )
    assert result.applicability == TransitionApplicability.APPLICABLE
    assert result.verdict == case["expected"], result.to_dict()
    assert result.cas_result["evidence_grade"] == CASEvidenceGrade.EXACT
    if result.verdict == TransitionVerdict.EQUIVALENT:
        assert result.cas_result["verified_exact"]
        assert result.witness is None
    else:
        assert result.witness is not None
        assert result.basis == CASBasis.EXACT_COUNTEREXAMPLE
        assert not result.cas_result["verified"]
    assert result.parent_revision == 3 and result.child_revision == 4
    assert result.parent_latex_sha256 == hashlib.sha256(case["before"].encode()).hexdigest()
    assert result.child_latex_sha256 == hashlib.sha256(case["after"].encode()).hexdigest()
    assert result.mode == "shadow" and not result.blocks_commit


def test_corpus_has_reproducible_full_pairs_and_declares_authorship():
    assert len(CORPUS["entries"]) == len({case["id"] for case in CORPUS["entries"]}) == 12
    assert CORPUS["source"] == "synthetic_author_reference"
    assert CORPUS["review_status"] == "agent-reviewed"


class UnexpectedChecker:
    def check(self, *_args, **_kwargs):
        raise AssertionError("non-applicable transition must not reach CAS")

    def close(self):
        pass


@pytest.mark.parametrize(
    "declared,parent,basis",
    [(False, 1, "transition_not_declared_preserving"), (True, None, "no_parent_revision")],
)
def test_candidate_generation_is_not_falsely_compared(declared, parent, basis):
    result = CASTransitionChecker(checker=UnexpectedChecker()).check(
        "x" if parent else None,
        "y",
        parent_revision=parent,
        child_revision=2,
        semantics_preserving_declared=declared,
    )
    assert result.verdict == TransitionVerdict.NOT_CHECKED
    assert result.applicability == TransitionApplicability.NOT_APPLICABLE
    assert result.basis == basis and not result.cas_result


@pytest.mark.parametrize(
    "latex",
    [
        r"\binom{x}{2}",
        r"\iint_0^1 x dx",
        r"\int_0^1 x dx",
        r"\sqrt{x}",
        r"\left|x\right|",
        r"\left[x\right]",
        r"\phantom{x}",
        r"\text{x}",
        r"\hat{x}",
        r"\mathbf{x}",
        r"x_i",
        r"\frac{x}{y}",
        r"\frac{x}{0}",
        "x/y",
        "12x",
        "x^{12}",
        "x^0",
        "x^{-1}",
        r"\sin(x)",
        r"\pi",
        "i+x",
        "e+x",
    ],
)
def test_unvalidated_scalar_notation_and_lossy_mapper_cases_are_not_proofs(latex):
    selected = CASTransitionChecker(checker=UnexpectedChecker())
    result = selected.check(
        latex, "x", parent_revision=1, child_revision=2, semantics_preserving_declared=True
    )
    assert result.verdict == TransitionVerdict.UNSUPPORTED, result.to_dict()
    assert result.applicability == TransitionApplicability.UNSUPPORTED
    assert result.witness is None and not result.cas_result


class ResultChecker:
    def __init__(self, status, basis):
        self.status = status
        self.basis = basis

    def check(self, *_args, **_kwargs):
        return CASResult(status=self.status, basis=self.basis)

    def close(self):
        pass


@pytest.mark.parametrize(
    "status,basis",
    [
        (CASStatus.UNKNOWN, CASBasis.INCONCLUSIVE),
        (CASStatus.TIMEOUT, CASBasis.WORKER_TIMEOUT),
        (CASStatus.UNAVAILABLE, CASBasis.CAPABILITY_UNAVAILABLE),
    ],
)
def test_nonproof_cas_outcomes_keep_their_typed_status(status, basis):
    selected = CASTransitionChecker(checker=ResultChecker(status, basis))
    result = selected.check(
        "x+1", "x+2", parent_revision=1, child_revision=2, semantics_preserving_declared=True
    )
    assert result.verdict == status.value
    assert result.basis == basis.value
    assert result.witness is None
    assert not result.cas_result["verified"]


def test_optional_cas_dependency_is_reported_unavailable(monkeypatch):
    monkeypatch.setattr(AlgebraChecker, "available", staticmethod(lambda: False))
    selected = CASTransitionChecker()
    try:
        result = selected.check(
            "x+1", "x+2", parent_revision=1, child_revision=2, semantics_preserving_declared=True
        )
    finally:
        selected.close()
    assert result.verdict == TransitionVerdict.UNAVAILABLE
    assert result.basis == CASBasis.CAPABILITY_UNAVAILABLE


def transition_state(before="x+1", after="x+2"):
    state = FormulaState(before)
    state.revise(after, expected_revision=1, origin="trusted-test-transition")
    state.add_evidence(
        revision=2,
        kind="mutation_scope",
        ok=True,
        output={
            "semantics_preserving_declared": True,
            "verdict": "allowed",
        },
    )
    return state


def test_shadow_difference_is_revision_bound_and_does_not_alter_commit_gate(checker):
    state = transition_state()
    checker.record(state)
    checker.record(state)
    evidence = [item for item in state.ledger.evidence if item.kind == "cas_transition"]
    assert len(evidence) == 2
    assert evidence[-1].revision == 2
    assert evidence[-1].output["verdict"] == "different"
    assert evidence[-1].output["witness"] is not None
    state.add_evidence(revision=2, kind="compile_tex", ok=True, output={"valid": True})
    state.add_evidence(revision=2, kind="render_math", ok=True)
    state.commit(expected_revision=2)
    assert state.committed  # The separate mutation scope gate remains runtime-owned.


class Planner:
    def __init__(self, turns):
        self.turns = list(turns)

    async def plan(self, *_args):
        return self.turns.pop(0)

    @staticmethod
    def extract_latex(content):
        return content


@pytest.mark.asyncio
async def test_real_runtime_syntax_repair_records_unsupported_parent_without_fake_proof(tmp_path):
    planner = Planner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="repair",
                        name="repair_tex",
                        arguments={"latex": r"\frac{x}{2"},
                    )
                ]
            ),
            PlannerTurn(content=r"\frac{x}{2}"),
        ]
    )
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate(
        "ocr", "synthetic.png", r"\frac{x}{2", initial_tokens_used=1
    )
    assert result.valid and result.committed
    evidence = [
        item for item in result.formula_ledger["evidence"] if item["kind"] == "cas_transition"
    ]
    assert evidence[-1]["output"]["verdict"] == "unsupported"
    assert evidence[-1]["output"]["parent_revision"] == 1
    assert evidence[-1]["output"]["child_revision"] == 2
    assert result.trace[-1]["cas_transition"] == [item["output"] for item in evidence]


@pytest.mark.asyncio
async def test_runtime_records_actual_repair_drift_while_scope_blocks_commit(tmp_path):
    pytest.importorskip("sympy")
    planner = Planner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="repair",
                        name="repair_tex",
                        arguments={"latex": "x+1", "expected_revision": 1},
                    )
                ]
            ),
            PlannerTurn(content="x+2"),
        ]
    )
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    execute = runtime.tools.execute

    async def drift(name, arguments):
        if name == "compile_tex" and arguments.get("latex") == "x+1":
            # An adversarial tool misreports the valid source as invalid, making
            # repair applicable. The independent raw AST scope/CAS checks must
            # still catch the subsequent mathematically changed repair result.
            return ToolObservation(name=name, ok=True, output={"valid": False})
        if name == "repair_tex":
            return ToolObservation(name=name, ok=True, output={"latex": "x+2", "valid": True})
        return await execute(name, arguments)

    runtime.tools.execute = drift
    result = await runtime.run_candidate("ocr", "synthetic.png", "x+1", initial_tokens_used=1)
    assert result.valid and not result.committed
    evidence = [
        item for item in result.formula_ledger["evidence"] if item["kind"] == "cas_transition"
    ]
    assert evidence[-1]["output"]["verdict"] == "different"
    assert evidence[-1]["output"]["basis"] == "exact_counterexample"
    assert evidence[-1]["output"]["scope_verdict"] == "out_of_scope"
    assert not evidence[-1]["output"]["blocks_commit"]


@pytest.mark.asyncio
async def test_shadow_uses_remaining_request_budget_and_ignores_late_thread_result(
    tmp_path, monkeypatch
):
    import texada.agent.runtime as runtime_module

    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path, tool_timeout_seconds=0.02))
    state = transition_state()
    original = CASTransitionChecker.evaluate
    completed = []

    def slow(self, current):
        time.sleep(0.1)
        completed.append(True)
        return original(self, current)

    monkeypatch.setattr(runtime_module.CASTransitionChecker, "evaluate", slow)
    started = time.monotonic()
    await runtime._record_cas_shadow(state, start=started)
    assert time.monotonic() - started < 0.08
    evidence = [item for item in state.ledger.evidence if item.kind == "cas_transition"]
    assert evidence[-1].output["verdict"] == "timeout"
    assert evidence[-1].output["basis"] == "request_or_tool_budget_exhausted"
    await asyncio.sleep(0.15)
    assert completed
    assert len([item for item in state.ledger.evidence if item.kind == "cas_transition"]) == 2


@pytest.mark.asyncio
async def test_exhausted_api_budget_does_not_start_cas_worker(tmp_path):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path, api_request_timeout_seconds=0.01))
    state = transition_state()
    await runtime._record_cas_shadow(state, start=time.monotonic() - 1)
    evidence = [item for item in state.ledger.evidence if item.kind == "cas_transition"]
    assert evidence[-1].output["verdict"] == "timeout"


@pytest.mark.asyncio
async def test_shadow_worker_failure_is_typed_unknown_without_aborting_runtime(
    tmp_path, monkeypatch
):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    state = transition_state()

    def fail(*_args):
        raise RuntimeError("private crash text")

    monkeypatch.setattr(CASTransitionChecker, "evaluate", fail)
    await runtime._record_cas_shadow(state, start=time.monotonic())
    evidence = [item for item in state.ledger.evidence if item.kind == "cas_transition"]
    assert evidence[-1].output["verdict"] == "unknown"
    assert evidence[-1].output["basis"] == "shadow_comparison_failed"
    assert "private" not in json.dumps(evidence[-1].to_dict())
