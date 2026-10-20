"""Regression tests for the removed NL/OCR/completion human-review gate.

Product decision (2026-10-20): NL, OCR and completion candidates commit
directly. The mutation-scope guard remains the only commit barrier, and the
Studio handoff surface (requires_review=True) remains the only producer of
pending reviews. High-risk role changes are still *reported* in
``review_reasons`` — as evidence, never as a commit gate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.api import create_app
from texada.config import TeXadaConfig


class Planner:
    def __init__(self, turns):
        self.turns = list(turns)

    async def plan(self, *_args):
        return self.turns.pop(0)

    async def generate_latex(
        self, user_input, intent, *, force_operators=None, deadline_monotonic=None,
    ):
        return r"\frac{a}{b}"

    @staticmethod
    def extract_latex(content):
        return content


def _runtime(tmp_path, turns):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=Planner(turns))
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    return runtime


def _denominator_drift_turns():
    return [
        PlannerTurn(tool_calls=[PlannerToolCall(
            "proposal", "propose_candidate", {"latex": r"\frac{a}{c}", "expected_revision": 1},
        )]),
        PlannerTurn(content=r"\frac{a}{c}"),
    ]


@pytest.mark.asyncio
async def test_nl_input_commits_directly_without_review(tmp_path):
    runtime = _runtime(tmp_path, [PlannerTurn(content=r"\frac{a}{b}")])

    result = await runtime.run(r"a over b")

    assert result.valid
    assert result.committed is True
    assert result.stop_reason != "human_review_required"
    assert result.review_reasons == []
    assert result.formula_ledger["commits"]


@pytest.mark.asyncio
async def test_ocr_input_commits_directly_without_review(tmp_path):
    runtime = _runtime(tmp_path, _denominator_drift_turns())

    result = await runtime.run_candidate(
        "ocr", "public-synthetic.png", r"\frac{a}{b}", initial_tokens_used=1,
        uncertain_role_paths=("root[0].denominator",),
    )

    assert result.valid
    assert result.committed is True
    assert result.stop_reason != "human_review_required"
    assert result.formula_ledger["commits"]


@pytest.mark.asyncio
async def test_high_risk_role_change_is_reported_but_still_commits(tmp_path):
    runtime = _runtime(tmp_path, _denominator_drift_turns())

    result = await runtime.run_candidate(
        "ocr", "public-synthetic.png", r"\frac{a}{b}", initial_tokens_used=1,
        uncertain_role_paths=("root[0].denominator",),
    )

    # Evidence is preserved; it just no longer blocks the commit.
    assert result.committed is True
    assert "high_risk_role_change" in result.review_reasons


@pytest.mark.asyncio
async def test_mutation_scope_violation_still_blocks_the_commit(tmp_path):
    runtime = _runtime(tmp_path, _denominator_drift_turns())

    result = await runtime.run_candidate(
        "ocr", "public-synthetic.png", r"\frac{a}{b}", initial_tokens_used=1,
    )

    assert result.valid
    assert result.committed is False
    assert result.stop_reason == "mutation_scope_review_required"
    assert result.formula_ledger["commits"] == []
    assert "mutation_scope_denied_or_uncertain" in result.review_reasons


@pytest.mark.asyncio
async def test_completion_deterministic_fast_path_respects_the_scope_guard(tmp_path):
    runtime = _runtime(tmp_path, [PlannerTurn(content="y+1")])

    result = await runtime.run_candidate("completion", "x", "y+1", initial_tokens_used=0)

    assert result.committed is False
    assert result.stop_reason == "mutation_scope_review_required"


@pytest.mark.asyncio
async def test_agent_endpoint_returns_no_review_and_records_history(tmp_path):
    app = create_app(TeXadaConfig(data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post("/api/agent", json={"text": "二重积分"})
        history = await client.get("/api/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["committed"] is True
    assert payload["review"] is None
    assert payload["stop_reason"] != "human_review_required"
    entries = history.json()
    assert isinstance(entries, list) and entries
