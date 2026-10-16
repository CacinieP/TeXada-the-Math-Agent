"""Release-blocker regressions: safe default adoption and bounded invalid-export recovery."""
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
async def test_default_nl_generation_requires_review_not_automatic_commit(tmp_path):
    engine, _ = runtime(tmp_path, [PlannerTurn(content='x+1')])
    result = await engine.run('a user-described formula')
    assert result.valid and not result.committed
    assert result.stop_reason == 'human_review_required'
    assert 'nl_semantics_requires_review' in result.review_reasons


@pytest.mark.asyncio
async def test_deterministic_nl_shortcut_cannot_bypass_default_review(tmp_path):
    engine = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    result = await engine.run('二重积分')
    assert result.valid and not result.committed
    assert 'nl_semantics_requires_review' in result.review_reasons


@pytest.mark.asyncio
async def test_legacy_automatic_mode_is_explicit_opt_in(tmp_path):
    engine, _ = runtime(tmp_path, [PlannerTurn(content='x+1')], nl_require_review=False)
    result = await engine.run('a user-described formula')
    assert result.valid and result.committed


@pytest.mark.asyncio
async def test_export_failure_has_one_fresh_bound_recovery_without_ocr_commit(tmp_path):
    engine, planner = runtime(tmp_path, [bad_export(), finish()], nl_require_review=False)
    result = await engine.run_candidate('ocr', 'synthetic source', 'x+1')
    assert result.valid and not result.committed
    assert result.stop_reason == 'human_review_required'
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
async def test_previously_auto_committed_differences_cannot_commit_unreviewed(tmp_path, row):
    engine, _ = runtime(tmp_path, [finish(), finish(), finish()])
    if requests_computation(row['input']):
        with pytest.raises(ComputationOutsideScope):
            await engine.run(row['input'], _initial_candidate=row['candidate'])
        return
    result = await engine.run(row['input'], _initial_candidate=row['candidate'])
    assert not result.committed
    if result.valid:
        assert 'nl_semantics_requires_review' in result.review_reasons
