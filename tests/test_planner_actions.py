"""Adversarial action proposals exercise the real runtime binding boundary."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from texada.agent.actions import ActionRejected, action_snapshot, bind_action, planner_schemas
from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.api import create_app
from texada.config import TeXadaConfig, save_config_updates
from texada.runtime import FormulaState
from texada.tools import TeXToolset, ToolRouter


def compiled_state(latex="x+1", *, valid=True):
    state = FormulaState(latex)
    state.add_evidence(revision=1, kind="compile_tex", ok=True, output={"valid": valid})
    return state


def test_surfaces_never_mutate_canonical_contracts(tmp_path):
    router = ToolRouter(TeXToolset(TeXadaConfig(data_dir=tmp_path)))
    original = deepcopy(router.schemas)
    snapshot = action_snapshot(FormulaState(), surface="minimal")
    minimal = planner_schemas(router.schemas, snapshot, surface="minimal")
    full = planner_schemas(router.schemas, snapshot, surface="full")
    assert [item["function"]["name"] for item in minimal] == ["propose_candidate"]
    assert len(full) == len(original) + 1
    full[0]["function"]["parameters"]["properties"]["latex"]["type"] = "null"
    assert router.schemas == original


@pytest.mark.parametrize("surface", ["full", "minimal"])
@pytest.mark.parametrize(
    ("valid", "required", "absent"),
    [
        (True, {"render_math", "export", "propose_candidate"}, {"repair_tex", "semantic_diff"}),
        (False, {"repair_tex"}, {"render_math", "export", "propose_candidate", "semantic_diff"}),
    ],
)
def test_mask_uses_only_current_revision_evidence(surface, valid, required, absent):
    state = compiled_state(valid=valid)
    assert action_snapshot(state, surface=surface).allowed >= required
    assert action_snapshot(state, surface=surface).allowed.isdisjoint(absent)
    state.revise("y+2", expected_revision=1, origin="user")
    mask = action_snapshot(state, surface=surface)
    assert "render_math" not in mask.allowed
    assert "repair_tex" not in mask.allowed
    assert "semantic_diff" in mask.allowed
    assert mask.before == "x+1"


@pytest.mark.parametrize(
    ("name", "arguments", "code"),
    [
        ("unknown", {}, "unknown_action"),
        ("compile_tex", {}, "missing_revision"),
        ("compile_tex", {"expected_revision": True}, "invalid_revision"),
        ("compile_tex", {"expected_revision": "1"}, "invalid_revision"),
        ("compile_tex", {"expected_revision": 0}, "invalid_revision"),
        ("compile_tex", {"expected_revision": 2}, "stale_revision"),
        ("compile_tex", {"expected_revision": 1, "latex": "x+1"}, "invalid_arguments"),
        ("semantic_diff", {"expected_revision": 1}, "action_not_applicable"),
        ("repair_tex", {"expected_revision": 1}, "action_not_applicable"),
        ("render_math", {"expected_revision": 1, "mode": "png"}, "invalid_arguments"),
        ("export", {"expected_revision": 1, "format": "pdf"}, "invalid_arguments"),
        ("propose_candidate", {"expected_revision": 1, "latex": ""}, "invalid_arguments"),
        ("propose_candidate", {"expected_revision": 1, "latex": 5}, "invalid_arguments"),
        ("propose_candidate", {"expected_revision": 1, "latex": "x" * 4001}, "invalid_arguments"),
    ],
)
def test_minimal_rejects_bad_proposals_before_dispatch(name, arguments, code):
    state = compiled_state()
    with pytest.raises(ActionRejected) as error:
        bind_action(
            PlannerToolCall("id", name, arguments),
            action_snapshot(state, surface="minimal"),
            state,
            surface="minimal",
        )
    assert error.value.code == code
    assert len(state.ledger.revisions) == 1


@pytest.mark.parametrize("name", ["compile_tex", "parse_tex", "render_math", "export"])
def test_full_mode_cannot_replace_authoritative_latex(name):
    state = compiled_state()
    with pytest.raises(ActionRejected, match="latex is owned"):
        bind_action(
            PlannerToolCall("id", name, {"latex": "malicious"}),
            action_snapshot(state, surface="full"),
            state,
            surface="full",
        )
    assert state.latex == "x+1"


@pytest.mark.parametrize("surface", ["full", "minimal"])
def test_diff_is_bound_to_immediate_parent_and_current(surface):
    state = compiled_state()
    state.revise("x+2", expected_revision=1, origin="user")
    snapshot = action_snapshot(state, surface=surface)
    arguments = {"expected_revision": 2}
    if surface == "full":
        arguments |= {"before": "x+1", "after": "x+2"}
    bound = bind_action(
        PlannerToolCall("id", "semantic_diff", arguments), snapshot, state, surface=surface
    )
    assert bound.call.arguments == {"before": "x+1", "after": "x+2"}
    if surface == "full":
        arguments["before"] = "invented"
        with pytest.raises(ActionRejected, match="before is owned"):
            bind_action(
                PlannerToolCall("id", "semantic_diff", arguments), snapshot, state, surface=surface
            )


@pytest.mark.parametrize("surface", ["full", "minimal"])
def test_same_batch_revision_change_never_rebinds_old_proposal(surface):
    state = compiled_state(valid=False)
    snapshot = action_snapshot(state, surface=surface)
    state.revise("x+2", expected_revision=1, origin="repair_tex")
    arguments = {"expected_revision": 1}
    if surface == "full":
        arguments["latex"] = "x+1"
    with pytest.raises(ActionRejected, match="current turn revision"):
        bind_action(
            PlannerToolCall("id", "compile_tex", arguments), snapshot, state, surface=surface
        )
    assert state.latex == "x+2"


def test_full_legacy_snapshot_is_recorded_and_seed_is_empty_state_only():
    state = FormulaState()
    bound = bind_action(
        PlannerToolCall("id", "compile_tex", {"latex": "x+1"}),
        action_snapshot(state, surface="full"),
        state,
        surface="full",
    )
    assert bound.initial_seed_bridge
    assert bound.revision_source == "runtime_turn_snapshot"
    assert state.revision is None  # Binding itself never changes state.
    state.revise(bound.candidate, expected_revision=None, origin="bridge")
    same = bind_action(
        PlannerToolCall("id", "compile_tex", {"latex": "x+1"}),
        action_snapshot(state, surface="full"),
        state,
        surface="full",
    )
    assert not same.initial_seed_bridge


class ScriptedPlanner:
    def __init__(self, turns):
        self.turns = list(turns)
        self.schemas = []
        self.generate_latex = AsyncMock(side_effect=AssertionError("No fallback after rejection"))

    async def plan(self, messages, tools):
        self.schemas.append(deepcopy(tools))
        return self.turns.pop(0)

    @staticmethod
    def extract_latex(content):
        return content.strip()


def call(name, revision, **kwargs):
    return PlannerToolCall(name, name, {"expected_revision": revision, **kwargs})


@pytest.mark.asyncio
async def test_minimal_explicit_candidate_compile_render_real_workflow(tmp_path):
    planner = ScriptedPlanner(
        [
            PlannerTurn(tool_calls=[call("propose_candidate", None, latex=r"\frac{x+1}{3}")]),
            PlannerTurn(tool_calls=[call("compile_tex", 1)]),
            PlannerTurn(tool_calls=[call("render_math", 1)]),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, planner_surface="minimal"), model=planner
    )
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run("format this expression")
    assert result.valid and result.committed
    assert result.latex == r"\frac{x+1}{3}"
    assert result.formula_ledger["revisions"][0]["origin"] == "planner:propose_candidate"
    for schemas in planner.schemas:
        for schema in schemas:
            function = schema["function"]
            if function["name"] != "propose_candidate":
                assert (
                    not {"latex", "before", "after"} & function["parameters"]["properties"].keys()
                )
    assert {s["function"]["name"] for s in planner.schemas[1]} == {
        "parse_tex",
        "compile_tex",
        "propose_candidate",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["full", "minimal"])
async def test_unknown_action_cannot_dispatch_or_trigger_compatibility_fallback(tmp_path, surface):
    planner = ScriptedPlanner([PlannerTurn(tool_calls=[call("execute_shell", None)])])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, planner_surface=surface), model=planner
    )
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime.tools.execute = AsyncMock(side_effect=AssertionError("must not dispatch"))
    result = await runtime.run("opaque request")
    assert result.stop_reason == "planner_action_rejected"
    assert not result.committed and not result.valid
    runtime.tools.execute.assert_not_awaited()
    planner.generate_latex.assert_not_awaited()


@pytest.mark.asyncio
async def test_proposal_then_compile_in_same_batch_is_stale_not_silently_rebound(tmp_path):
    planner = ScriptedPlanner(
        [
            PlannerTurn(
                tool_calls=[
                    call("propose_candidate", None, latex="x+1"),
                    call("compile_tex", None),
                ]
            )
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, planner_surface="minimal"), model=planner
    )
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime.tools.execute = AsyncMock(side_effect=AssertionError("stale inspection"))
    result = await runtime.run("opaque request")
    assert result.latex == "x+1" and result.revision == 1
    assert not result.committed
    assert result.trace[-1]["observations"][0]["output"]["code"] == "stale_revision"
    runtime.tools.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_minimal_bare_final_cannot_seed_formula(tmp_path):
    planner = ScriptedPlanner([PlannerTurn(content="x+1")])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, planner_surface="minimal"), model=planner
    )
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run("opaque request")
    assert result.revision is None and not result.committed
    assert result.trace[-1]["observations"][0]["output"]["code"] == "explicit_proposal_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["full", "minimal"])
async def test_bare_final_cannot_replace_already_compiled_and_rendered_state(
    tmp_path, monkeypatch, surface,
):
    from texada.agent import runtime as runtime_module

    planner = ScriptedPlanner([PlannerTurn(content="y+2")])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, planner_surface=surface), model=planner,
    )
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    state = FormulaState("x+1")
    for name in ("compile_tex", "render_math"):
        observation = await runtime.tools.execute(name, {"latex": state.latex})
        assert observation.ok
        state.add_evidence(revision=1, kind=name, ok=observation.ok, output=observation.output)
    before = deepcopy(state.to_dict())
    # Resume the genuine tool-validated state through the actual run loop.
    monkeypatch.setattr(runtime_module, "FormulaState", lambda *args, **kwargs: state)
    result = await runtime.run("opaque request")
    assert result.latex == "x+1" and result.revision == 1
    assert result.stop_reason == "planner_action_rejected"
    assert not result.valid and not result.committed
    assert state.to_dict() == before
    assert result.formula_ledger == before
    assert result.trace[-1]["observations"][0]["output"]["code"] == "explicit_proposal_required"


@pytest.mark.asyncio
async def test_full_empty_direct_final_seed_is_explicitly_recorded(tmp_path):
    planner = ScriptedPlanner([PlannerTurn(content="x+1")])
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run("opaque request")
    assert result.valid and result.committed
    assert result.formula_ledger["revisions"][0]["origin"] == "full_initial_final_seed_bridge"
    assert result.trace[0]["action_bindings"] == [{
        "id": "full-direct-final-seed", "revision": None,
        "revision_source": "runtime_final_seed", "initial_seed_bridge": True,
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize("latex", [
    r"\text{LaTeX: x}+y",
    r"\text{Final LaTeX: x}+y",
    r"\text{Candidate LaTeX: x}+y",
    r"\text{Candidate LaTeX (authoritative starting state): x}+y",
])
async def test_full_compile_and_render_preserve_authoritative_literal_labels(tmp_path, latex):
    planner = ScriptedPlanner([
        PlannerTurn(tool_calls=[call("compile_tex", 1, latex=latex)]),
        PlannerTurn(tool_calls=[call("render_math", 1, latex=latex, mode="katex")]),
    ])
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run("public synthetic formula", _task="ocr", _initial_candidate=latex)
    assert result.valid and result.committed
    assert result.latex == latex and result.revision == 1
    assert len(result.formula_ledger["revisions"]) == 1
    assert '<span class="katex">' in result.render.katex_html
    for item in result.trace:
        if item["origin"] == "planner":
            assert item["raw_tool_calls"][0]["arguments"]["latex"] == latex
            assert item["tool_calls"][0]["arguments"]["latex"] == latex
            assert item["observations"][0]["ok"]


@pytest.mark.parametrize(("source", "expected"), [
    (r"\text{LaTeX: x}+y", r"\text{LaTeX: x}+y"),
    (r"\text{Final LaTeX: x}+y", r"\text{Final LaTeX: x}+y"),
    (r"LaTeX: \text{LaTeX: x}+y", r"\text{LaTeX: x}+y"),
    (r"Final LaTeX: $\text{LaTeX: x}+y$", r"\text{LaTeX: x}+y"),
    (r"LaTeX: x+1", "x+1"),
])
def test_prompt_label_normalization_only_removes_a_leading_label(tmp_path, source, expected):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    assert runtime._sanitize_latex_argument(source) == expected


def test_exact_historical_diff_bindings_keep_literal_labels(tmp_path):
    state = FormulaState(r"\text{LaTeX: x}+1")
    state.revise(r"\text{Final LaTeX: x}+2", expected_revision=1, origin="proposal")
    snapshot = action_snapshot(state, surface="full")
    proposal = call("semantic_diff", 2, before=snapshot.before, after=snapshot.latex)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    normalized = runtime._normalize_call(proposal, authority=snapshot)
    assert normalized.arguments == proposal.arguments
    bound = bind_action(normalized, snapshot, state, surface="full")
    assert bound.call.arguments == {"before": snapshot.before, "after": snapshot.latex}


def test_even_a_leading_label_in_authority_is_not_rewritten_as_a_model_prompt(tmp_path):
    state = FormulaState("LaTeX: x+y")
    snapshot = action_snapshot(state, surface="full")
    proposal = call("compile_tex", 1, latex=state.latex)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    normalized = runtime._normalize_call(proposal, authority=snapshot)
    assert normalized.arguments == proposal.arguments
    bound = bind_action(normalized, snapshot, state, surface="full")
    assert bound.call.arguments == {"latex": state.latex}
    # This asserts binding only; the actual compiler may reject this non-formula.


def test_surface_setting_is_persisted_exposed_and_reversible(tmp_path):
    config = save_config_updates({"planner_surface": "minimal"}, tmp_path)
    assert config.planner_surface == "minimal"
    app = create_app(config)
    with TestClient(app) as client:
        assert client.get("/api/settings/backend").json()["planner_surface"] == "minimal"
        assert (
            client.post("/api/settings/backend", json={"planner_surface": "full"}).json()[
                "planner_surface"
            ]
            == "full"
        )
        assert (
            client.post("/api/settings/backend", json={"planner_surface": "unsafe"}).status_code
            == 422
        )
        exported = client.get("/api/export").json()
        assert exported["settings"]["planner_surface"] == "full"
