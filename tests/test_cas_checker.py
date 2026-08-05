"""Conservative CAS policy and process-isolation tests."""

from __future__ import annotations

import multiprocessing
import time
from typing import Any

import pytest

from texada.cas import (
    AlgebraChecker,
    CASBasis,
    CASEvidenceGrade,
    CASResult,
    CASStatus,
    CASWorker,
    CASWorkerMemoryExceeded,
    CASWorkerTimeout,
    build_cache_key,
)
from texada.cas.policy import compare_expressions
from texada.semantic import SemanticParser

sp = pytest.importorskip("sympy")


class _UnexpectedWorker:
    def compare(self, *_: Any, **__: Any) -> CASResult:
        raise AssertionError("unsupported input must not reach the comparator")

    def close(self) -> None:
        pass


class _TimeoutWorker:
    def compare(self, *_: Any, **__: Any) -> CASResult:
        raise CASWorkerTimeout("injected timeout")

    def close(self) -> None:
        pass


class _MemoryLimitWorker:
    def compare(self, *_: Any, **__: Any) -> CASResult:
        raise CASWorkerMemoryExceeded(
            peak_rss_bytes=1024,
            limit_bytes=512,
        )

    def close(self) -> None:
        pass


def _controllable_worker(inbox: Any, outbox: Any) -> None:
    outbox.put({"ready": True})
    while True:
        request = inbox.get()
        if request.get("operation") == "stop":
            return
        if "hang" in request.get("assumptions", []):
            time.sleep(10)
            continue
        result = CASResult(
            status=CASStatus.UNKNOWN,
            basis=CASBasis.INCONCLUSIVE,
            reason_code="test_response",
        )
        outbox.put(
            {
                "id": request["id"],
                "ok": True,
                "result": result.to_dict(),
            }
        )


def test_exact_counterexample_requires_finite_values():
    x = sp.Symbol("x")

    result = compare_expressions(1 / x, 2 / x)

    assert result.status is CASStatus.DIFFERENT
    assert result.basis is CASBasis.EXACT_COUNTEREXAMPLE
    assert result.evidence_grade is CASEvidenceGrade.EXACT
    assert result.witness != {"x": 0}
    assert result.lhs_value not in {"zoo", "oo", "nan"}
    assert result.rhs_value not in {"zoo", "oo", "nan"}


def test_equals_false_remains_observation_without_exact_witness():
    x = sp.Symbol("x")
    polynomial = sp.prod(x - value for value in (0, 1, -1, 2, -2))
    assert polynomial.equals(0) is False

    result = compare_expressions(polynomial, sp.Integer(0))

    assert result.status is CASStatus.UNKNOWN
    assert result.basis is CASBasis.SYMPY_EQUALS_FALSE_OBSERVATION
    assert result.evidence_grade is CASEvidenceGrade.OBSERVATION
    assert result.observation["equals"] is False


def test_unsafe_nonfinite_evaluation_is_unknown_not_different():
    k = sp.Symbol("k", integer=True, positive=True)

    result = compare_expressions(sp.Sum(1 / k, (k, 1, sp.oo)), sp.oo)

    assert result.status is CASStatus.UNKNOWN
    assert result.basis is CASBasis.UNSAFE_EVALUATION_RESULT
    assert result.reason_code == "non_finite_result"
    assert result.observation["lhs_convergence"] == "divergent"


def test_convergence_is_auxiliary_evidence_not_an_infinity_comparison():
    k = sp.Symbol("k", integer=True, positive=True)

    result = compare_expressions(
        sp.Sum(1 / k**2, (k, 1, sp.oo)),
        sp.pi**2 / 6,
    )

    assert result.status is CASStatus.EQUIVALENT
    assert result.observation["lhs_convergence"] == "convergent"


@pytest.mark.parametrize(
    "relation",
    [
        lambda x: sp.Gt(x, 3),
        lambda x: sp.Ge(x, 3),
        lambda x: sp.Lt(x, 3),
        lambda x: sp.Le(x, 3),
        lambda x: sp.Ne(x, 3),
    ],
)
def test_non_equality_relations_are_unsupported_without_raising(relation):
    x = sp.Symbol("x")

    result = compare_expressions(relation(x), relation(x))

    assert result.status is CASStatus.UNSUPPORTED
    assert result.basis is CASBasis.UNSUPPORTED_SEMANTIC_UNIT
    assert result.evidence_grade is CASEvidenceGrade.NONE
    assert result.reason_code == "unsupported_relation"


def test_unsupported_semantic_unit_never_reaches_worker():
    parser = SemanticParser()
    checker = AlgebraChecker(worker=_UnexpectedWorker())

    result = checker.check(parser.parse(r"\hat{H}"), parser.parse("H"))

    assert result.status is CASStatus.UNSUPPORTED
    assert result.reason_code == "unsupported_command"


def test_worker_timeout_maps_to_auditable_status():
    parser = SemanticParser()
    checker = AlgebraChecker(worker=_TimeoutWorker())

    result = checker.check(parser.parse("x+1"), parser.parse("x+1"))

    assert result.status is CASStatus.TIMEOUT
    assert result.basis is CASBasis.WORKER_TIMEOUT
    assert result.verified is False


def test_worker_memory_limit_maps_to_auditable_status():
    parser = SemanticParser()
    checker = AlgebraChecker(worker=_MemoryLimitWorker())

    result = checker.check(parser.parse("x+1"), parser.parse("x+1"))

    assert result.status is CASStatus.UNKNOWN
    assert result.basis is CASBasis.WORKER_MEMORY_LIMIT
    assert result.reason_code == "worker_memory_limit"
    assert result.observation["peak_rss_bytes"] == 1024


def test_process_timeout_kills_worker_and_next_request_restarts_it():
    context = multiprocessing.get_context("spawn")
    worker = CASWorker(
        timeout_ms=100,
        startup_timeout_ms=10_000,
        context=context,
        target=_controllable_worker,
    )
    try:
        with pytest.raises(CASWorkerTimeout):
            worker.compare(sp.Integer(1), sp.Integer(1), assumptions=["hang"])
        assert worker.pid is None

        result = worker.compare(sp.Integer(1), sp.Integer(1))

        assert result.reason_code == "test_response"
        assert worker.pid is not None
    finally:
        worker.close()


def test_parent_pid_rss_limit_kills_worker():
    context = multiprocessing.get_context("spawn")
    worker = CASWorker(
        timeout_ms=1000,
        startup_timeout_ms=10_000,
        max_rss_bytes=1,
        rss_poll_interval_ms=20,
        context=context,
        target=_controllable_worker,
    )
    try:
        with pytest.raises(CASWorkerMemoryExceeded) as captured:
            worker.compare(sp.Integer(1), sp.Integer(1), assumptions=["hang"])

        assert captured.value.peak_rss_bytes > captured.value.limit_bytes
        assert worker.pid is None
    finally:
        worker.close()


def test_worker_resets_sympy_seed_for_every_task():
    x = sp.Symbol("x")
    mask = sp.prod(x - value for value in (0, 1, -1, 2, -2))
    lhs = (sp.sqrt(x**2) - x) * mask

    with CASWorker(timeout_ms=1000) as worker:
        first = worker.compare(lhs, sp.Integer(0), seed=0)
        second = worker.compare(lhs, sp.Integer(0), seed=0)
        different_seed = worker.compare(lhs, sp.Integer(0), seed=1)

    assert first.seed == second.seed == 0
    assert first.basis is second.basis
    assert first.observation.get("equals") == second.observation.get("equals")
    assert different_seed.seed == 1
    assert (
        first.basis,
        first.observation.get("equals"),
    ) != (
        different_seed.basis,
        different_seed.observation.get("equals"),
    )


def test_cache_key_canonicalizes_assumptions_and_tracks_seed_and_versions():
    parser = SemanticParser()
    lhs = parser.parse("x+1")
    rhs = parser.parse("1+x")
    common = {
        "lhs": lhs,
        "rhs": rhs,
        "sympy_version": sp.__version__,
        "policy_version": "cas-policy-v2",
    }

    first = build_cache_key(
        **common,
        assumptions={"x": {"real": True, "positive": False}},
        seed=0,
    )
    reordered = build_cache_key(
        **common,
        assumptions={"x": {"positive": False, "real": True}},
        seed=0,
    )
    different_seed = build_cache_key(
        **common,
        assumptions={"x": {"real": True, "positive": False}},
        seed=1,
    )

    assert first == reordered
    assert first != different_seed


def test_missing_sympy_is_capability_unavailable(monkeypatch):
    parser = SemanticParser()
    checker = AlgebraChecker(worker=_UnexpectedWorker())
    monkeypatch.setattr(checker, "available", lambda: False)

    result = checker.check(parser.parse("x"), parser.parse("x"))

    assert result.status is CASStatus.UNAVAILABLE
    assert result.basis is CASBasis.CAPABILITY_UNAVAILABLE
