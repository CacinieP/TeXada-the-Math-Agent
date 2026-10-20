"""Release-blocker regressions: direct candidate adoption and bounded invalid-export recovery.

NL / OCR / completion candidates now commit directly: the human-review gate was
removed for those surfaces, so a committed run carries no pending review and the
``MutationScopeGuard`` stays the only commit barrier. The Studio handoff surface
still opts into review explicitly and is covered by its own tests.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.scope import ComputationOutsideScope, requests_computation


class Planner:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.calls = 0

    async def plan(self, messages, tools):
        self.calls += 1
        return next(self.turns)

    @staticmethod
    def extract_latex(content):
        return content.strip()


def runtime(tmp_path, turns, **settings):
    settings.setdefault("nl_candidate_first", False)
    planner = Planner(turns)
    engine = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path, **settings), model=planner)
    engine.backend.ensure_ready = AsyncMock(return_value=True)
    engine.candidate_engine.propose = lambda text: None
    return engine, planner


def finish(revision=1):
    return PlannerTurn(tool_calls=[PlannerToolCall(
        'finish', 'finish_formula', {'expected_revision': revision},
    )])


def bad_export(revision=1, latex='x+1'):
    return PlannerTurn(tool_calls=[PlannerToolCall(
        'bad', 'export', {'latex': latex, 'format': 'bare', 'expected_revision': revision},
    )])


@pytest.mark.asyncio
async def test_default_nl_generation_commits_directly(tmp_path):
    engine, _ = runtime(tmp_path, [PlannerTurn(content='x+1')])
    result = await engine.run('a user-described formula')
    assert result.valid and result.committed
    assert result.stop_reason == 'planner_final'
    assert result.review_reasons == []
    assert result.formula_ledger['commits']


@pytest.mark.asyncio
async def test_deterministic_nl_shortcut_commits_directly(tmp_path):
    engine = TeXadaAgentRuntime(TeXadaConfig(nl_candidate_first=False, data_dir=tmp_path))
    result = await engine.run('二重积分')
    assert result.valid and result.committed
    assert result.stop_reason == 'deterministic_candidate'
    assert result.review_reasons == []


@pytest.mark.asyncio
async def test_handoff_requires_review_still_blocks_automatic_commit(tmp_path):
    engine, _ = runtime(tmp_path, [
        PlannerTurn(tool_calls=[PlannerToolCall(
            'seed', 'compile_tex', {'latex': '7+5'},
        )]),
        finish(),
    ])
    result = await engine.run('输入 7+5', _requires_review=True)
    assert result.valid and not result.committed
    assert result.stop_reason == 'human_review_required'
    assert 'trusted_review_required' in result.review_reasons


@pytest.mark.asyncio
async def test_export_failure_has_one_fresh_bound_recovery_with_ocr_commit(tmp_path):
    engine, planner = runtime(tmp_path, [bad_export(), finish()])
    result = await engine.run_candidate('ocr', 'synthetic source', 'x+1')
    assert result.valid and result.committed
    assert result.stop_reason == 'finish_confirmed'
    assert planner.calls == 2
    errors = [o for t in result.trace for o in t.get('observations', [])
              if o.get('error') == 'Invalid export format']
    assert len(errors) == 1
    assert all(e['ok'] is False for e in errors)
    assert not any(e['kind'] == 'export' and e['output'].get('format') == 'bare'
                   for e in result.formula_ledger.get('evidence', []))


@pytest.mark.asyncio
@pytest.mark.parametrize('turns,steps', [([bad_export(), bad_export()], 3), ([bad_export()], 1)])
async def test_repeated_or_budget_exhausted_invalid_export_is_not_success(tmp_path, turns, steps):
    engine, planner = runtime(tmp_path, turns, agent_max_steps=steps)
    result = await engine.run_candidate('ocr', 'synthetic source', 'x+1')
    assert not result.committed and not result.valid
    assert result.stop_reason == 'planner_action_rejected'
    assert planner.calls == len(turns)


@pytest.mark.asyncio
@pytest.mark.parametrize('proposal', [bad_export(revision=2), bad_export(latex='y+2')])
async def test_recovery_never_accepts_stale_revision_or_value_override(tmp_path, proposal):
    engine, planner = runtime(tmp_path, [proposal, finish()])
    result = await engine.run_candidate('ocr', 'synthetic source', 'x+1')
    assert result.stop_reason == 'planner_action_rejected'
    assert not result.committed and planner.calls == 1


AUDIT = json.loads((Path(__file__).parents[1] / 'eval/beta4-difference-audit.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('row', AUDIT['entries'], ids=lambda r: r['case_id'])
async def test_previously_auto_committed_differences_commit_directly(tmp_path, row):
    engine, _ = runtime(tmp_path, [finish(), finish(), finish()])
    if requests_computation(row['input']):
        with pytest.raises(ComputationOutsideScope):
            await engine.run(row['input'], _initial_candidate=row['candidate'])
        return
    result = await engine.run(row['input'], _initial_candidate=row['candidate'])
    assert result.valid and result.committed
    assert result.stop_reason == 'finish_confirmed'
    assert result.review_reasons == []
    assert result.formula_ledger['commits']


@pytest.mark.asyncio
async def test_default_planner_bootstraps_candidate_before_inspection(tmp_path):
    turns = [PlannerTurn(tool_calls=[PlannerToolCall(
        'seed', 'compile_tex', {'latex': '7+5'},
    )]), finish()]
    engine, planner = runtime(tmp_path, turns)
    result = await engine.run('输入 7+5')
    assert result.latex == '7+5' and result.valid
    assert result.committed and planner.calls == 2
    assert result.stop_reason == 'finish_confirmed'
    assert result.review_reasons == []


@pytest.mark.asyncio
async def test_builtin_default_generates_candidate_before_planning_and_commits_directly(tmp_path):
    planner = Planner([finish()])
    planner.generate_latex = AsyncMock(return_value='7+5')
    engine = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    engine.backend.ensure_ready = AsyncMock(return_value=True)
    engine.candidate_engine.propose = lambda text: None
    assert engine.config.nl_candidate_first is True
    result = await engine.run('输入 7+5')
    planner.generate_latex.assert_awaited_once()
    assert result.latex == '7+5' and result.valid and result.committed
    assert result.stop_reason == 'finish_confirmed'
    assert result.review_reasons == []


@pytest.mark.asyncio
async def test_agent_endpoint_committed_run_writes_history_without_review(tmp_path, monkeypatch):
    """A committed NL run returns no review payload and lands in history."""
    from fastapi.testclient import TestClient

    from texada.agent.runtime import AgentRunResult
    from texada.api import create_app
    from texada.render.engine import RenderEngine

    config = TeXadaConfig(data_dir=tmp_path)

    async def fake_run(self, user_input, *, context="", render_mode=None):
        return AgentRunResult(
            latex=r"\frac{a}{b}",
            valid=True,
            render=RenderEngine(config).render(r"\frac{a}{b}"),
            semantic_document={"latex": r"\frac{a}{b}", "root": {"kind": "sequence"}},
            trace=[{"step": 1, "origin": "planner"}],
            stop_reason="planner_final",
            revision=2,
            committed=True,
        )

    monkeypatch.setattr(TeXadaAgentRuntime, "run", fake_run)

    client = TestClient(create_app(config))
    response = client.post(
        "/api/agent",
        json={"text": "a divided by b", "render_mode": "katex"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["committed"] is True
    assert body["review"] is None

    history = client.get("/api/history").json()
    assert [entry["latex"] for entry in history] == [r"\frac{a}{b}"]
