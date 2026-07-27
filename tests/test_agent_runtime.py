"""Planner → Tool → Observation runtime tests."""
import json
from unittest.mock import AsyncMock

import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.types import RenderMode


class FakePlanner:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen_messages = []

    async def plan(self, messages, tools):
        self.seen_messages.append(messages)
        assert {item["function"]["name"] for item in tools} >= {
            "compile_tex",
            "repair_tex",
            "render_math",
        }
        return self.turns.pop(0)

    async def generate_latex(self, user_input, intent, *, force_operators=None):
        return "x+1"

    @staticmethod
    def extract_latex(content):
        return content.strip()


def disable_deterministic_candidates(runtime):
    """Keep legacy planner/guard tests focused on the fallback path."""
    runtime.candidate_engine.propose = lambda _text: None


@pytest.mark.asyncio
async def test_runtime_executes_multistep_tools_and_repairs_only_through_tool(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="compile_1",
                        name="compile_tex",
                        arguments={"latex": r"\frac{a}{b"},
                    )
                ]
            ),
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="repair_1",
                        name="repair_tex",
                        arguments={"latex": r"\frac{a}{b"},
                    )
                ]
            ),
            PlannerTurn(content=r"\frac{a}{b}", tokens_used=7),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("a divided by b", render_mode=RenderMode.KATEX)

    assert result.latex == r"\frac{a}{b}"
    assert result.valid
    assert result.semantic_diff["change_count"] >= 1
    assert [item["origin"] for item in result.trace] == [
        "planner",
        "planner",
        "planner",
        "runtime_guard",
    ]
    repair_observation = result.trace[1]["observations"][0]
    assert repair_observation["tool"] == "repair_tex"
    assert repair_observation["output"]["repair_method"] == "deterministic-rules"
    assert planner.seen_messages[-1][-1]["role"] == "tool"
    serialized_trace = json.dumps(result.trace)
    assert "katex_html" not in serialized_trace
    assert "latex_highlighted" not in serialized_trace
    tool_message = planner.seen_messages[-1][-1]
    assert "katex_html" not in tool_message["content"]


@pytest.mark.asyncio
async def test_runtime_accepts_direct_final_then_applies_guard_tools(tmp_path):
    planner = FakePlanner([PlannerTurn(content=r"\sqrt{x}")])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("square root of x", render_mode=RenderMode.LATEX)

    assert result.latex == r"\sqrt{x}"
    assert result.valid
    assert result.stop_reason == "planner_final"
    assert result.render.latex_highlighted
    assert result.trace[-1]["origin"] == "runtime_guard"


@pytest.mark.asyncio
async def test_runtime_uses_zero_model_range_sum_fast_path(tmp_path):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("求k从1到n的k平方")

    assert result.latex == r"\sum_{k=1}^{n} k^2"
    assert result.valid is True
    assert result.tokens_used == 0
    assert result.stop_reason == "deterministic_candidate"
    assert result.trace[0]["origin"] == "deterministic_candidate"
    assert result.trace[0]["candidate_rule"] == "nl_range_sum"
    assert [
        call["name"] for call in result.trace[0]["tool_calls"]
    ] == ["compile_tex", "render_math"]
    assert planner.seen_messages == []
    runtime.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_restores_inline_bare_sum_without_model(tmp_path):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(
        "求k从1到n的k平方 sum_{k=1}^{n} k^2"
    )

    assert result.latex == r"\sum_{k=1}^{n} k^2"
    assert result.trace[0]["candidate_rule"] == "inline_latex_hint"
    assert planner.seen_messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected", "rule"),
    [
        (
            "偏导 u 关于 x",
            r"\frac{\partial u}{\partial x}",
            "nl_partial_derivative",
        ),
        (
            "x趋向0时 sin x 除以 x 的极限",
            r"\lim_{x\to 0} \frac{\sin x}{x}",
            "nl_quotient_limit",
        ),
        (
            "二重积分 f(x,y) 在区域 D 上",
            r"\iint_{D} f(x,y)\,dx\,dy",
            "nl_multiple_integral",
        ),
        (
            "a除以b",
            r"\frac{a}{b}",
            "nl_simple_division",
        ),
        (
            "2乘3等于6",
            r"2\times 3=6",
            "nl_simple_equality",
        ),
        (
            "x与y之和的平方",
            "(x+y)^2",
            "nl_sum_power",
        ),
        (
            "根号下 x 加 1",
            r"\sqrt{x+1}",
            "nl_simple_radical",
        ),
    ],
)
async def test_runtime_uses_structured_math_fast_paths(
    tmp_path,
    text,
    expected,
    rule,
):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(text)

    assert result.latex == expected
    assert result.valid is True
    assert result.tokens_used == 0
    assert result.trace[0]["candidate_rule"] == rule
    assert planner.seen_messages == []
    runtime.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_normalizes_render_mode_and_stops_after_render(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="render_case_variant",
                        name="render_math",
                        arguments={
                            "latex": "x^2",
                            "mode": "kaTeX",
                        },
                    )
                ]
            )
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("x squared")

    assert result.latex == "x^2"
    assert result.valid is True
    assert result.stop_reason == "render_confirmed"
    assert len(planner.seen_messages) == 1
    call = result.trace[0]["tool_calls"][0]
    assert call["arguments"]["mode"] == "katex"


@pytest.mark.asyncio
async def test_ocr_candidate_enters_planner_with_compile_observation(tmp_path):
    planner = FakePlanner(
        [PlannerTurn(content=r"\int_0^1 x\,dx", tokens_used=3)]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run_candidate(
        "ocr",
        "formula.png",
        r"\int_0^1 x\,dx",
        initial_tokens_used=11,
    )

    assert result.latex == r"\int_0^1 x\,dx"
    assert result.tokens_used == 14
    assert [item["origin"] for item in result.trace] == [
        "candidate_intake",
        "planner",
        "runtime_guard",
    ]
    intake = result.trace[0]
    assert intake["task"] == "ocr"
    assert intake["tool_calls"][0]["name"] == "compile_tex"
    assert intake["observations"][0]["output"]["valid"] is True
    first_messages = planner.seen_messages[0]
    assert "OCR review task" in first_messages[0]["content"]
    assert first_messages[2]["tool_calls"][0]["function"]["name"] == "compile_tex"
    assert first_messages[3]["role"] == "tool"


@pytest.mark.asyncio
async def test_completion_candidate_is_repaired_via_tool_not_planner_text(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="repair_completion",
                        name="repair_tex",
                        arguments={"latex": r"\frac{a}{b"},
                    )
                ]
            ),
            PlannerTurn(content=r"\frac{a}{b}"),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run_candidate(
        "completion",
        r"\frac{a}{",
        r"\frac{a}{b",
    )

    assert result.latex == r"\frac{a}{b}"
    assert result.valid is True
    assert result.trace[0]["observations"][0]["output"]["valid"] is False
    assert result.trace[1]["tool_calls"][0]["name"] == "repair_tex"
    assert result.semantic_diff["change_count"] >= 1
    assert "formula-completion review task" in planner.seen_messages[0][0]["content"]


@pytest.mark.asyncio
async def test_deterministic_completion_candidate_skips_planner(tmp_path):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run_candidate(
        "completion",
        r"\sum_{i=1}^{",
        r"\sum_{i=1}^{n} x_i",
        initial_tokens_used=0,
    )

    assert result.latex == r"\sum_{i=1}^{n} x_i"
    assert result.valid is True
    assert result.tokens_used == 0
    assert result.stop_reason == "deterministic_candidate"
    assert result.trace[0]["task"] == "completion"
    assert result.trace[0]["candidate_rule"] == "completion_deterministic"
    assert planner.seen_messages == []
    runtime.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_breaks_repeated_identical_tool_call(tmp_path):
    repeated_call = PlannerToolCall(
        id="compile_repeat",
        name="compile_tex",
        arguments={"latex": "x+1"},
    )
    planner = FakePlanner(
        [
            PlannerTurn(tool_calls=[repeated_call]),
            PlannerTurn(tool_calls=[repeated_call]),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("x plus one")

    assert result.stop_reason == "repeated_tool_call"
    blocked = result.trace[1]["observations"][0]
    assert not blocked["ok"]
    assert "Repeated identical tool call" in blocked["error"]


@pytest.mark.asyncio
async def test_runtime_falls_back_after_two_consecutive_tool_errors(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(id="bad_1", name="not_a_tool", arguments={})
                ]
            ),
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(id="bad_2", name="still_not_a_tool", arguments={})
                ]
            ),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("x plus one")

    assert result.stop_reason == "tool_error_limit"
    assert result.latex == "x+1"
    assert any(item["origin"] == "compatibility_fallback" for item in result.trace)


@pytest.mark.asyncio
async def test_runtime_preserves_symbol_engine_operator_anchor(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(content=r"\int_D f(x,y)\,dx\,dy"),
            PlannerTurn(content=r"\iint_D f(x,y)\,dx\,dy"),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_D f(x,y)\,dx\,dy"
    assert result.stop_reason == "operator_drift_deterministic_restore"
    drift_observation = result.trace[0]["observations"][0]
    assert drift_observation["tool"] == "operator_drift_guard"
    assert drift_observation["output"]["required_operators"] == [r"\iint"]
    assert len(planner.seen_messages) == 1
    first_prompt = planner.seen_messages[0][1]["content"]
    assert r"\iint f(x,y) 在区域 D 上" in first_prompt


@pytest.mark.asyncio
async def test_runtime_uses_deterministic_integral_restore_before_model_retry(tmp_path):
    planner = FakePlanner(
        [PlannerTurn(content="x^2+y^2") for _ in range(3)]
    )
    planner.generate_latex = AsyncMock(
        return_value=r"\iint_D f(x,y)\,dx\,dy"
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.stop_reason == "operator_drift_deterministic_restore"
    assert len(planner.seen_messages) == 1
    planner.generate_latex.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_keeps_constrained_retry_for_non_synthesizable_operators(tmp_path):
    planner = FakePlanner([PlannerTurn(content="u") for _ in range(2)])
    planner.generate_latex = AsyncMock(
        return_value=r"\frac{\partial u}{\partial x}"
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("偏导 u")

    assert result.latex == r"\frac{\partial u}{\partial x}"
    assert result.stop_reason == "operator_drift_recovered"
    assert result.trace[-2]["origin"] == "operator_drift_fallback"
    planner.generate_latex.assert_awaited_once()
    assert planner.generate_latex.await_args.kwargs["force_operators"] == [
        r"\frac",
        r"\partial",
    ]


@pytest.mark.asyncio
async def test_runtime_uses_deterministic_integral_fallback_after_empty_retry(tmp_path):
    planner = FakePlanner(
        [PlannerTurn(content="二重积分 f(x,y) 在区域 D 上") for _ in range(3)]
    )
    planner.generate_latex = AsyncMock(return_value="...")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.valid is True
    assert result.stop_reason == "operator_drift_deterministic_restore"
    restored = result.trace[-2]["observations"][-1]
    assert restored["output"]["method"] == "deterministic_integral_rank_restore"


@pytest.mark.asyncio
async def test_runtime_short_circuits_exact_user_echo_with_anchor_fallback(tmp_path):
    planner = FakePlanner(
        [PlannerTurn(content="二重积分 f(x,y) 在区域 D 上")]
    )
    planner.generate_latex = AsyncMock(return_value="must not run")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.valid is True
    assert result.stop_reason == "operator_drift_deterministic_restore"
    planner.generate_latex.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_uses_anchor_fallback_after_empty_first_turn(tmp_path):
    planner = FakePlanner([PlannerTurn(content="")])
    planner.generate_latex = AsyncMock(return_value="must not run")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.stop_reason == "operator_drift_deterministic_restore"
    assert result.trace[-2]["origin"] == "deterministic_anchor_fallback"
    planner.generate_latex.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_restores_integral_domain_after_compile_observation(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(
                tool_calls=[
                    PlannerToolCall(
                        id="compile_integral",
                        name="compile_tex",
                        arguments={
                            "latex": r"\iint f(x,y) dx dy in region D",
                        },
                    )
                ]
            )
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二重积分 f(x,y) 在区域 D 上")

    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.stop_reason == "operator_drift_deterministic_restore"
    assert len(planner.seen_messages) == 1
