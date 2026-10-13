"""Role drift counterexamples and runtime commit behavior, without inference."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from texada.agent.mutation_scope import MutationScopeGuard, MutationVerdict
from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.semantic import SemanticDiffer


def assess(before, after, *, task="ocr", origin="planner_final", roles=(), prefix=""):
    return MutationScopeGuard(task=task, prefix=prefix, uncertain_roles=roles).assess(
        before,
        after,
        origin=origin,
        parent_revision=1,
        child_revision=2,
    )


@pytest.mark.parametrize(
    ("before", "after", "role"),
    [
        (r"\frac{a}{b}", r"\frac{a}{c}", "denominator"),
        (r"\frac{a}{b}", r"\frac{c}{b}", "numerator"),
        (r"\int_0^1 x dx", r"\int_0^2 x dx", "upper_bound"),
        (r"\int_0^1 x dx", r"\int_1^1 x dx", "lower_bound"),
        (r"\iint_D f", r"\int_D f", "base"),
        (r"x_i", r"x_j", "subscript"),
        (r"x^2", r"x^3", "superscript"),
        (r"\sqrt[3]{x}", r"\sqrt[2]{x}", "index"),
    ],
)
def test_recognized_math_roles_cannot_drift_without_ocr_authorization(before, after, role):
    result = assess(before, after)
    assert result.verdict == MutationVerdict.OUT_OF_SCOPE
    assert any(role in change["path"] for change in result.footprint), result.to_dict()
    assert result.parent_revision == 1 and result.child_revision == 2
    assert result.authorized_role_paths == []
    assert any(change["role"] == role for change in result.footprint)


def test_ocr_uncertainty_grant_is_exact_role_and_cannot_expand_to_numerator():
    allowed = assess(r"\frac{a}{b}", r"\frac{a}{c}", roles=("root[0].denominator",))
    assert allowed.verdict == MutationVerdict.ALLOWED
    blocked = assess(r"\frac{a}{b}", r"\frac{x}{c}", roles=("root[0].denominator",))
    assert blocked.verdict == MutationVerdict.OUT_OF_SCOPE
    assert any("numerator" in item["path"] for item in blocked.footprint)


@pytest.mark.parametrize(
    "path", ["root", "denominator", "root[0]", "root[0].children", "root[0].denominator*"]
)
def test_ocr_grants_require_a_complete_canonical_role_path(path):
    with pytest.raises(ValueError, match="complete mathematical role"):
        MutationScopeGuard(task="ocr", uncertain_roles=(path,))


def test_syntax_repair_can_close_missing_braces_but_cannot_change_math():
    allowed = assess(r"\frac{a}{b", r"\frac{a}{b}", origin="tool:repair_tex")
    assert allowed.verdict == MutationVerdict.ALLOWED
    assert allowed.basis == "deterministic_trailing_closing_braces"
    assert allowed.semantics_preserving_declared
    blocked = assess(r"\frac{a}{b}", r"\frac{a}{c}", origin="tool:repair_tex")
    assert blocked.verdict == MutationVerdict.OUT_OF_SCOPE
    ambiguous = assess(r"\frac{a}{b", r"\frac{a}{c}", origin="tool:repair_tex")
    assert ambiguous.verdict == MutationVerdict.REVIEW_REQUIRED


def test_formatting_is_authorized_only_when_pinned_tree_really_matches():
    assert assess(r"\frac{a}{b}", r"\dfrac{{a}}{{b}}\,").verdict == MutationVerdict.ALLOWED
    assert assess(r"\binom{a}{b}", r"\frac{a}{b}").verdict == MutationVerdict.OUT_OF_SCOPE


def test_completion_retains_entire_prefix_including_bounds_scripts_and_tokens():
    prefix = r"\sum_{i=1}^{n} x_i"
    allowed = assess(prefix + "+1", prefix + "+2", task="completion", prefix=prefix)
    assert allowed.verdict == MutationVerdict.ALLOWED
    blocked = assess(prefix + "+1", r"\sum_{j=1}^{n} x_j+2", task="completion", prefix=prefix)
    assert blocked.verdict == MutationVerdict.OUT_OF_SCOPE
    # An invalid prefix still has a token-level invariant.
    assert (
        assess(
            r"\frac{a}{b",
            r"\frac{a}{b}",
            task="completion",
            prefix=r"\frac{a}{",
            origin="tool:repair_tex",
        ).verdict
        == MutationVerdict.ALLOWED
    )


@pytest.mark.parametrize(
    "after", [r"\phantom{x}+y", r"\text{x}+y", r"\unknown{x}+y", "{" * 101 + "x" + "}" * 101]
)
def test_unreliable_parse_does_not_authorize_mutation(after):
    assert assess("x+y", after).verdict == MutationVerdict.REVIEW_REQUIRED


def test_degraded_alignment_has_explicit_review_path_even_with_a_role_grant():
    before = r"\frac{x}{" + "+".join(["y"] * 101) + "}"
    after = r"\frac{x}{" + "+".join(["z"] * 101) + "}"
    assert SemanticDiffer().diff(before, after).degraded
    result = assess(before, after, roles=("root[0].denominator",))
    assert result.verdict == MutationVerdict.REVIEW_REQUIRED
    assert result.basis == "unreliable_parse_or_diff"


def test_nl_synthesis_grant_does_not_claim_intent_or_semantic_equivalence():
    result = assess("x", "y", task="nl")
    assert result.verdict == MutationVerdict.ALLOWED
    assert result.transition == "candidate_synthesis"
    assert result.intent_status == "NOT_CHECKED"
    assert not result.semantics_preserving_declared
    assert result.footprint


class Planner:
    def __init__(self, turns):
        self.turns = list(turns)

    async def plan(self, *_args):
        return self.turns.pop(0)

    @staticmethod
    def extract_latex(content):
        return content


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted_roles,committed", [((), False), (("root[0].denominator",), True)])
async def test_runtime_blocks_ungranted_ocr_commit_but_records_role_footprint(
    tmp_path, trusted_roles, committed
):
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path), model=Planner([PlannerTurn(content=r"\frac{a}{c}")])
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate(
        "ocr",
        "public-synthetic.png",
        r"\frac{a}{b}",
        initial_tokens_used=1,
        uncertain_role_paths=trusted_roles,
    )
    assert result.valid
    assert result.committed is committed
    changes = [
        item for item in result.formula_ledger["evidence"] if item["kind"] == "mutation_scope"
    ]
    assert len(changes) == 2
    assert changes[-1]["output"]["parent_revision"] == 1
    assert changes[-1]["output"]["child_revision"] == 2
    assert changes[-1]["output"]["footprint"]
    assert result.trace[-1]["mutation_scope"] == [item["output"] for item in changes]
    if not committed:
        assert result.stop_reason == "mutation_scope_review_required"
        assert result.formula_ledger["commits"] == []


@pytest.mark.asyncio
async def test_planner_extra_role_permissions_do_not_become_runtime_grants(tmp_path):
    turn = PlannerTurn(
        tool_calls=[
            PlannerToolCall(
                id="forged",
                name="compile_tex",
                arguments={
                    "latex": r"\frac{a}{c}",
                    "uncertain_role_paths": ["root[0].denominator"],
                },
            )
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path), model=Planner([turn, PlannerTurn(content=r"\frac{a}{c}")])
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate("ocr", "public.png", r"\frac{a}{b}", initial_tokens_used=1)
    assert not result.committed
    assert all(
        item["output"]["authorized_role_paths"] == []
        for item in result.formula_ledger["evidence"]
        if item["kind"] == "mutation_scope"
    )


@pytest.mark.asyncio
async def test_completion_deterministic_fast_path_cannot_replace_source_prefix(tmp_path):
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path), model=Planner([PlannerTurn(content="y+1")])
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate("completion", "x", "y+1", initial_tokens_used=0)
    assert not result.committed
    assert result.stop_reason == "mutation_scope_review_required"


@pytest.mark.asyncio
async def test_later_restoration_does_not_erase_unauthorized_transition(tmp_path):
    turns = [
        PlannerTurn(
            tool_calls=[
                PlannerToolCall(id="changed", name="compile_tex", arguments={"latex": r"x_j"})
            ]
        ),
        PlannerTurn(content="x_i"),
    ]
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=Planner(turns))
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate("ocr", "public.png", "x_i", initial_tokens_used=1)
    assert result.latex == "x_i"
    assert not result.committed
    assert any(
        not item["ok"]
        for item in result.formula_ledger["evidence"]
        if item["kind"] == "mutation_scope"
    )
