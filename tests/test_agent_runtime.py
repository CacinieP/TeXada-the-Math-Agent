"""Planner → Tool → Observation runtime tests."""
import json
from unittest.mock import AsyncMock, Mock

import pytest

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.tools import ToolObservation
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

    async def generate_latex(
        self, user_input, intent, *, force_operators=None, deadline_monotonic=None,
    ):
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
    planner_observation = json.loads(tool_message["content"])
    assert planner_observation["revision"] == 1
    assert planner_observation["formula_state"]["revision"] == 2
    assert planner_observation["formula_state"]["latex"] == r"\frac{a}{b}"
    assert '"root"' not in tool_message["content"]
    assert "semantic_document" not in tool_message["content"]
    assert result.revision == 2
    assert result.committed is True
    assert result.formula_ledger["current_revision"] == 2
    assert all(
        item["revision"] in {1, 2}
        for item in result.formula_ledger["evidence"]
    )
    assert result.formula_ledger["commits"][0]["revision"] == 2


@pytest.mark.asyncio
async def test_runtime_accepts_direct_final_then_applies_guard_tools(tmp_path):
    planner = FakePlanner([PlannerTurn(content=r"\sqrt{x}")])
    planner.generate_latex = AsyncMock(side_effect=AssertionError("flag is off"))
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
    assert result.trace[0]["origin"] == "planner"
    planner.generate_latex.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_returns_invalid_final_with_diagnostics_after_repair(tmp_path):
    planner = FakePlanner([PlannerTurn(content="...")])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("unknown request")

    assert result.valid is False
    assert result.latex == "..."
    assert result.stop_reason == "validation_failed_after_repair"
    guard = result.trace[-1]
    assert guard["origin"] == "runtime_guard"
    assert guard["content"] == "..."
    assert [item["tool"] for item in guard["observations"]] == [
        "compile_tex",
        "repair_tex",
        "compile_tex",
    ]
    assert any(
        diagnostic["type"] == "non_formula_content"
        for item in guard["observations"]
        for diagnostic in item.get("output", {}).get("diagnostics", [])
    )


@pytest.mark.asyncio
async def test_runtime_returns_controlled_result_for_empty_formula_state(tmp_path):
    planner = FakePlanner([PlannerTurn(content="")])
    planner.generate_latex = AsyncMock(return_value="")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("piecewise request with no model output")

    assert result.latex == ""
    assert result.valid is False
    assert result.committed is False
    assert result.revision is None
    assert result.stop_reason == "empty_formula_state"
    assert result.trace[-1]["origin"] == "runtime_guard"
    assert result.trace[-1]["observations"][0]["tool"] == "runtime_policy"


@pytest.mark.asyncio
async def test_runtime_returns_controlled_result_for_model_timeout(tmp_path):
    planner = FakePlanner([])
    planner.plan = AsyncMock(side_effect=RuntimeError("model request timed out"))
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("set expression")

    assert result.valid is False
    assert result.committed is False
    assert result.stop_reason == "model_request_failed"
    assert result.trace[-2]["origin"] == "planner_error"
    assert result.trace[-1]["origin"] == "runtime_guard"


@pytest.mark.asyncio
async def test_runtime_stops_before_starting_a_model_call_without_budget(tmp_path):
    planner = FakePlanner([PlannerTurn(content="must not run")])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime._model_call_budget_available = lambda _start: False

    result = await runtime.run("request that would exceed the bridge budget")

    assert result.valid is False
    assert result.committed is False
    assert result.stop_reason == "runtime_budget_exhausted"
    assert planner.seen_messages == []


@pytest.mark.asyncio
async def test_runtime_does_not_commit_unresolved_request_anchors(tmp_path):
    planner = FakePlanner(
        [PlannerTurn(content="tan(nu)"), PlannerTurn(content="tan(nu)")]
    )
    planner.generate_latex = AsyncMock(return_value="tan(nu)")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(
        "Express the tangent function applied to lowercase Greek letter nu."
    )

    assert result.valid is False
    assert result.committed is False
    assert result.stop_reason == "semantic_anchor_unresolved"
    guard = result.trace[-1]["observations"][0]
    assert guard["tool"] == "operator_drift_guard"
    assert guard["output"]["missing_requirements"] == [r"\tan", r"\nu"]


@pytest.mark.asyncio
async def test_runtime_recovers_request_anchors_before_commit(tmp_path):
    planner = FakePlanner(
        [
            PlannerTurn(content="tan(nu)"),
            PlannerTurn(tool_calls=[PlannerToolCall(
                id="explicit_anchor_proposal", name="propose_candidate",
                arguments={"latex": r"\tan(\nu)", "expected_revision": 1},
            )]),
            PlannerTurn(content=r"\tan(\nu)"),
        ]
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(
        "Express the tangent function applied to lowercase Greek letter nu."
    )

    assert result.latex == r"\tan(\nu)"
    assert result.valid is True
    assert not result.committed
    assert "structural_shape_change" in result.review_reasons
    first_prompt = planner.seen_messages[0][1]["content"]
    assert "Runtime request anchors" in first_prompt
    assert r"- \tan" in first_prompt
    assert r"- \nu" in first_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
async def test_runtime_uses_zero_model_range_sum_fast_path(tmp_path, candidate_first):
    planner = FakePlanner([])
    planner.generate_latex = AsyncMock(side_effect=AssertionError("zero-model path"))
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first),
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
    planner.generate_latex.assert_not_awaited()
    runtime.backend.ensure_ready.assert_not_awaited()
    assert result.revision == 1
    assert result.committed is True
    assert {
        item["kind"] for item in result.formula_ledger["evidence"]
    } == {"compile_tex", "render_math", "mutation_scope", "cas_transition"}


@pytest.mark.asyncio
async def test_runtime_uses_zero_model_named_concept_fast_path(tmp_path):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("贝叶斯公式")

    assert result.valid is True
    assert result.tokens_used == 0
    assert result.trace[0]["candidate_rule"] == "nl_canonical_concept"
    assert r"\frac" in result.latex
    assert planner.seen_messages == []
    runtime.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "required"),
    [
        ("二重积分", (r"\iint", r"\placeholder")),
        ("三重积分", (r"\iiint", r"\placeholder")),
        ("分段函数", (r"\begin{cases}", r"\placeholder")),
    ],
)
async def test_runtime_uses_zero_model_structural_concepts(
    tmp_path,
    text,
    required,
):
    planner = FakePlanner([])
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(text)

    assert result.valid is True
    assert result.tokens_used == 0
    assert result.stop_reason == "deterministic_candidate"
    assert all(fragment in result.latex for fragment in required)
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
        (
            "Write the sum of u and f.",
            "u+f",
            "nl_simple_sum_en",
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
            PlannerTurn(tool_calls=[PlannerToolCall(
                id="compile_before_render", name="compile_tex", arguments={"latex": "x^2"},
            )]),
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
    assert len(planner.seen_messages) == 2
    call = result.trace[1]["tool_calls"][0]
    assert call["arguments"]["mode"] == "katex"


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
async def test_ocr_candidate_enters_planner_with_compile_observation(tmp_path, candidate_first):
    planner = FakePlanner(
        [PlannerTurn(content=r"\int_0^1 x\,dx", tokens_used=3)]
    )
    planner.generate_latex = AsyncMock(side_effect=AssertionError("OCR already has a candidate"))
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first),
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
    planner.generate_latex.assert_not_awaited()
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
    intake_projection = json.loads(first_messages[3]["content"])
    assert intake_projection["revision"] == 1
    assert "semantic_document" not in first_messages[3]["content"]
    assert intake_projection["output"]["semantic_summary"]["root_kind"] == (
        "sequence"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
async def test_completion_candidate_is_repaired_via_tool_not_planner_text(
    tmp_path, candidate_first,
):
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
    planner.generate_latex = AsyncMock(
        side_effect=AssertionError("completion already has a candidate"),
    )
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first),
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
    planner.generate_latex.assert_not_awaited()
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
async def test_runtime_rejects_unknown_actions_without_compatibility_fallback(tmp_path):
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

    assert result.stop_reason == "planner_action_rejected"
    assert result.latex == ""
    assert result.committed is False
    assert not any(item["origin"] == "compatibility_fallback" for item in result.trace)


@pytest.mark.asyncio
async def test_runtime_compatibility_fallback_uses_detected_intent(tmp_path):
    planner = FakePlanner(
        [PlannerTurn()]
    )
    planner.generate_latex = AsyncMock(return_value=r"\det(A)")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("矩阵 A 的行列式")

    assert result.latex == r"\det(A)"
    assert planner.generate_latex.await_args.args[1] == "matrix"


def test_runtime_sanitizes_prompt_labels_in_tool_arguments(tmp_path):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    normalized = runtime._normalize_call(
        PlannerToolCall(
            id="compile_label_leak",
            name="compile_tex",
            arguments={
                "latex": (
                    "Deterministic symbol translation (authoritative):\n"
                    r"\sum_{i=1}^{n}i"
                )
            },
        )
    )

    assert normalized.arguments["latex"] == r"\sum_{i=1}^{n}i"


@pytest.mark.asyncio
@pytest.mark.parametrize(("opening", "closing"), [
    ("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]"),
])
async def test_wrapped_planner_tool_arguments_compile_render_and_commit(tmp_path, opening, closing):
    latex = r"\sum_{k=2}^{m}\frac{a_k+b_k}{\sqrt{k+1}}"
    planner = FakePlanner([
        PlannerTurn(tool_calls=[PlannerToolCall(
            id=f"wrapped_{name}", name=name,
            arguments={"latex": f"{opening}{latex}{closing}"},
        )])
        # Only compile can seed an empty full state; parse inspects an existing revision.
        for name in ("compile_tex", "parse_tex", "render_math")
    ])
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("请排版这个有限求和。")

    assert len(planner.seen_messages) == 3
    assert result.latex == latex
    assert result.valid is True
    assert result.committed is True
    assert result.semantic_document["parser_backend"].startswith("katex-")
    assert '<span class="katex">' in result.render.katex_html
    assert result.render.copy_text == f"$${latex}$$"
    for step in result.trace[:3]:
        assert step["tool_calls"][0]["arguments"]["latex"] == latex
        assert step["observations"][0]["ok"] is True


@pytest.mark.asyncio
async def test_wrapped_sum_replay_commits_after_the_observed_repeated_compile(tmp_path):
    latex = r"\sum_{k=2}^{m}\frac{a_k+b_k}{\sqrt{k+1}}"
    planner = FakePlanner([
        PlannerTurn(tool_calls=[PlannerToolCall(
            id=f"observed_{index}", name=name, arguments={"latex": f"${latex}$"},
        )])
        for index, name in enumerate(("compile_tex", "parse_tex", "compile_tex"))
    ])
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("请排版这个有限求和。")

    assert result.latex == latex
    assert result.valid is True
    assert result.committed is True
    assert '<span class="katex">' in result.render.katex_html
    assert "Repeated identical tool call" in result.trace[2]["observations"][0]["error"]
    assert [observation["tool"] for observation in result.trace[-1]["observations"]] == [
        "compile_tex", "render_math",
    ]


@pytest.mark.parametrize(("source", "expected"), [
    (r"$\text{price: \$5}$", r"\text{price: \$5}"),
    (r"\(\text{price: \$5}\)", r"\text{price: \$5}"),
    ("  LaTeX: $ x+1 $  ", "x+1"),
    (r"\$x\$", r"\$x\$"),
    (r"$x\$", r"$x\$"),
    (r"$x\\$", r"x\\"),
    (r"$x$ + $y$", r"$x$ + $y$"),
    (r"$$x$$ $$y$$", r"$$x$$ $$y$$"),
    (r"\(x\) + \(y\)", r"\(x\) + \(y\)"),
    (r"\[x\]\[y\]", r"\[x\]\[y\]"),
    (r"$x$ and text", r"$x$ and text"),
    (r"prefix $x$", r"prefix $x$"),
    (r"$x$y$", r"$x$y$"),
    (r"$$x$", r"$$x$"),
    (r"\(x\]", r"\(x\]"),
    (r"\[x + $y$\]", r"\[x + $y$\]"),
    (r"$$", r"$$"),
    (r"\(\)", r"\(\)"),
])
def test_tool_argument_wrapper_boundaries_preserve_content(tmp_path, source, expected):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    assert runtime._sanitize_latex_argument(source) == expected


def test_non_candidate_tool_outputs_do_not_replace_latest_latex(tmp_path):
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path))
    observation = ToolObservation(
        name="parse_tex",
        ok=True,
        output={"semantic_document": {"latex": "wrong"}},
    )

    assert runtime._latest_latex("kept", "parse_tex", observation) == "kept"


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
    assert result.stop_reason == "human_review_required"
    assert not result.committed and result.review_reasons
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
    assert result.stop_reason == "human_review_required"
    assert "structural_shape_change" in result.review_reasons
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
    assert result.stop_reason == "human_review_required"
    assert "structural_shape_change" in result.review_reasons
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
    assert result.stop_reason == "human_review_required"
    assert not result.committed and result.review_reasons
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
    assert result.stop_reason == "human_review_required"
    assert not result.committed and result.review_reasons
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
    assert result.stop_reason == "human_review_required"
    assert "structural_shape_change" in result.review_reasons
    assert len(planner.seen_messages) == 1


@pytest.mark.asyncio
async def test_nl_candidate_first_generates_then_compiles_before_shared_planner(tmp_path):
    candidate = r"\tan(\nu)"
    user_input = "Express the tangent function applied to lowercase Greek letter nu."
    planner = FakePlanner([PlannerTurn(content=candidate, tokens_used=5)])
    events = []

    async def generate(*args, **kwargs):
        events.append("generate")
        return f"  {candidate}\n"

    planner.generate_latex = AsyncMock(side_effect=generate)
    planner.consume_tokens_used = Mock(return_value=11)
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="openai_compatible",
        openai_base_url="https://api.modelbest.cn/v1",
        openai_api_key="test-placeholder",
        openai_model_name="MiniCPM-V-4.7-1B",
        openai_vision_model_name="",
        nl_candidate_first=True,
    )
    runtime = TeXadaAgentRuntime(config, model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime._model_call_budget_available = Mock(wraps=runtime._model_call_budget_available)
    execute = runtime.tools.execute
    plan = planner.plan

    async def record_tool(name, arguments):
        events.append(name)
        return await execute(name, arguments)

    async def record_plan(messages, tools):
        events.append("plan")
        return await plan(messages, tools)

    runtime.tools.execute = record_tool
    planner.plan = record_plan

    result = await runtime.run(user_input, context="Keep the Greek letter lowercase.")

    assert events[:3] == ["generate", "compile_tex", "plan"]
    assert runtime.model is planner
    assert config.active_model_name == config.active_vision_model_name == "MiniCPM-V-4.7-1B"
    planner.generate_latex.assert_awaited_once_with(
        user_input,
        "generic",
        force_operators=[r"\tan", r"\nu"],
        deadline_monotonic=(
            runtime._model_call_budget_available.call_args_list[0].args[0]
            + config.api_request_timeout_seconds
        ),
    )
    assert result.tokens_used == 16
    assert result.valid and result.committed
    assert result.formula_ledger["revisions"][0]["origin"] == "nl_candidate"
    assert result.formula_ledger["revisions"][0]["latex"] == candidate
    assert [item["origin"] for item in result.trace] == [
        "candidate_intake", "planner", "runtime_guard",
    ]
    assert result.trace[0]["tool_calls"][0]["arguments"] == {"latex": candidate}
    messages = planner.seen_messages[0]
    assert "natural-language candidate review task" in messages[0]["content"]
    assert "Task: NL candidate review" in messages[1]["content"]
    assert f"User request:\n{user_input}" in messages[1]["content"]
    assert "Keep the Greek letter lowercase." in messages[1]["content"]
    assert r"- \tan" in messages[1]["content"]
    assert r"- \nu" in messages[1]["content"]
    intake = json.loads(messages[3]["content"])
    assert intake["revision"] == 1
    assert intake["formula_state"]["latex"] == candidate


@pytest.mark.asyncio
async def test_nl_candidate_first_preserves_original_symbol_anchors_when_candidate_drifts(tmp_path):
    user_input = "二重积分 f(x,y) 在区域 D 上"
    planner = FakePlanner([PlannerTurn(content="x^2")])
    planner.generate_latex = AsyncMock(return_value="x^2")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=True),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(user_input)

    planner.generate_latex.assert_awaited_once()
    assert planner.generate_latex.await_args.args == (r"\iint f(x,y) 在区域 D 上", "integral")
    assert planner.generate_latex.await_args.kwargs["force_operators"] == [r"\iint"]
    prompt = planner.seen_messages[0][1]["content"]
    assert user_input in prompt
    assert "Deterministic symbol translation (authoritative):" in prompt
    assert r"\iint f(x,y) 在区域 D 上" in prompt
    assert r"- \iint" in prompt
    assert result.trace[1]["preprocessed_input"] == r"\iint f(x,y) 在区域 D 上"
    assert result.latex == r"\iint_{D} f(x,y)\,dx\,dy"
    assert result.valid and not result.committed
    assert "structural_shape_change" in result.review_reasons


@pytest.mark.asyncio
async def test_nl_candidate_first_repairs_invalid_candidate_only_through_deterministic_tool(
    tmp_path,
):
    planner = FakePlanner([
        PlannerTurn(tool_calls=[PlannerToolCall(
            id="repair_invalid_candidate", name="repair_tex",
            arguments={"latex": r"\frac{a}{b", "expected_revision": 1},
        )]),
        PlannerTurn(content=r"\frac{a}{b}"),
    ])
    planner.generate_latex = AsyncMock(return_value=r"\frac{a}{b")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=True),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("a divided by b")

    planner.generate_latex.assert_awaited_once()
    assert result.trace[0]["observations"][0]["output"]["valid"] is False
    assert result.trace[1]["tool_calls"][0]["name"] == "repair_tex"
    repairs = [
        item for step in result.trace for item in step["observations"]
        if item["tool"] == "repair_tex"
    ]
    assert repairs and repairs[0]["output"]["repair_method"] == "deterministic-rules"
    assert result.latex == r"\frac{a}{b}"
    assert result.valid and result.committed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    " \n", RuntimeError("candidate request timed out"), TimeoutError("candidate budget exhausted"),
])
async def test_nl_candidate_first_failure_has_no_formula_revision_or_tool_input(tmp_path, failure):
    planner = FakePlanner([])
    planner.generate_latex = (
        AsyncMock(side_effect=failure)
        if isinstance(failure, Exception)
        else AsyncMock(return_value=failure)
    )
    planner.consume_tokens_used = Mock(return_value=13)
    planner.plan = AsyncMock()
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=True),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime.tools.execute = AsyncMock()

    result = await runtime.run("natural-language request requiring a candidate")

    assert result.stop_reason == (
        "runtime_budget_exhausted" if isinstance(failure, TimeoutError) else "model_request_failed"
    )
    assert result.latex == ""
    assert result.valid is False and result.committed is False
    assert result.revision is None
    assert result.formula_ledger["revisions"] == []
    assert result.formula_ledger["commits"] == []
    assert result.tokens_used == 13
    runtime.tools.execute.assert_not_awaited()
    planner.plan.assert_not_awaited()
    if isinstance(failure, str):
        assert "empty formula" in result.trace[-1]["observations"][0]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("budgets", [[False], [True, False]])
async def test_nl_candidate_first_and_planner_share_original_request_budget(tmp_path, budgets):
    planner = FakePlanner([])
    planner.generate_latex = AsyncMock(return_value="x+1")
    planner.consume_tokens_used = Mock(return_value=7)
    planner.plan = AsyncMock()
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=True),
        model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime._model_call_budget_available = Mock(side_effect=budgets)

    result = await runtime.run("natural-language request requiring a candidate")

    assert result.stop_reason == "runtime_budget_exhausted"
    assert result.valid is False and result.committed is False
    planner.plan.assert_not_awaited()
    if budgets[0]:
        planner.generate_latex.assert_awaited_once()
        calls = runtime._model_call_budget_available.call_args_list
        assert calls[0].args[0] == calls[1].args[0]
        assert planner.generate_latex.await_args.kwargs["deadline_monotonic"] == (
            calls[0].args[0] + runtime.config.api_request_timeout_seconds
        )
        assert result.tokens_used == 7
        assert result.formula_ledger["revisions"][0]["origin"] == "nl_candidate"
        assert result.trace[0]["origin"] == "candidate_intake"
        assert result.formula_ledger["commits"] == []
    else:
        planner.generate_latex.assert_not_awaited()
        assert result.tokens_used == 0
        assert result.revision is None


@pytest.mark.asyncio
async def test_runtime_blocks_human_review_case_096_missing_intersection(tmp_path):
    # Replay the reviewed candidate without calling or changing a model.
    candidate = r"A \cup B = \{x | x \in A \text{ 或 } x \in B\}"
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("集合 A 与集合 B 的并集和交集")

    assert not result.committed
    assert result.stop_reason == "semantic_anchor_unresolved"
    guard = result.trace[-1]["observations"][0]
    assert guard["output"]["missing_requirements"] == [r"\cap"]
    assert r"\cap" not in result.latex  # The guard must not invent the missing formula.


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,label,candidate,required", [
    ("046", "上", r"\lim_{n \to \infty} a_{n}", r"\limsup"),
    ("047", "下", r"\lim_{n \to \infty} a_n", r"\liminf"),
])
async def test_runtime_blocks_reviewed_sequence_limit_downgrades(
    tmp_path, case_id, label, candidate, required,
):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(f"数列 a 下标 n 的{label}极限")

    assert not result.committed, case_id
    assert result.stop_reason == "semantic_anchor_unresolved"
    assert required in result.trace[-1]["observations"][0]["output"]["missing_requirements"]
    assert required not in result.latex  # No fabricated replacement formula.


@pytest.mark.asyncio
@pytest.mark.parametrize("label,candidate", [
    ("上", r"\limsup_{n\to\infty} a_n"),
    ("下", r"\liminf_{n\to\infty} a_n"),
])
async def test_runtime_keeps_explicit_sequence_limit_notation(tmp_path, label, candidate):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(f"数列 a 下标 n 的{label}极限")

    assert result.valid
    assert result.committed
    assert result.latex == candidate


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate,should_commit", [
    (r"\oint_C f\,ds", False),
    (r"\int_C f\,ds", True),
])
async def test_runtime_preserves_unspecified_curve_closure(tmp_path, candidate, should_commit):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("沿曲线 C 的线积分 f ds")

    assert result.committed is should_commit
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"
        assert result.latex == candidate  # No silent change of curve assumptions.


@pytest.mark.asyncio
@pytest.mark.parametrize("description", [
    "沿闭合曲线 C 的线积分 f ds",
    "沿曲线 C 的闭合线积分 f ds",
])
async def test_runtime_keeps_explicit_closed_curve_integrals(tmp_path, description):
    candidate = r"\oint_C f\,ds"
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(description)

    assert result.valid
    assert result.committed
    assert result.latex == candidate


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate,should_commit", [
    (r"\frac{d^n f}{dx}", False),
    (r"\frac{d^n f}{dx^n}", True),
    (r"f^{(n)}(x)", True),
])
async def test_runtime_preserves_nth_derivative_description(tmp_path, candidate, should_commit):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("f 对 x 的 n 阶导数")

    assert result.committed is should_commit
    assert result.latex == candidate
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate,should_commit", [
    (r"\frac{\partial y}{\partial x}", False),
    (r"\frac{\partial^2 y}{\partial x^2}", False),
    (r"\frac{dy}{dx}", False),
    (r"\frac{d^2y}{dx^2}", True),
    ("y''(x)", True),
    (r"y^{(2)}(x)", True),
])
async def test_runtime_preserves_second_ordinary_derivative(
    tmp_path, candidate, should_commit,
):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("y 对 x 的二阶导数")

    assert result.committed is should_commit
    assert result.latex == candidate  # Reject rather than compute or rewrite.
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate,should_commit", [
    (r"\det\begin{pmatrix} a & b \\ c & d \end{pmatrix} = ad - bc", False),
    (r"\begin{pmatrix}a&b\\c&d\end{pmatrix}", True),
    (r"\begin{bmatrix}a&b\\c&d\end{bmatrix}", True),
])
async def test_runtime_preserves_literal_matrix_description(tmp_path, candidate, should_commit):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(TeXadaConfig(data_dir=tmp_path), model=planner)
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("二乘二矩阵，第一行 a b，第二行 c d")

    assert result.committed is should_commit
    assert result.latex == candidate
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"
        assert result.formula_ledger["commits"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.parametrize("candidate,should_commit", [
    (
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix} \times "
        r"\begin{pmatrix} e & f \\ g & h \end{pmatrix} = "
        r"\begin{pmatrix} ae+bg & af+bh \\ ce+dg & cg+dh \end{pmatrix}",
        False,
    ),
    ("AB", True),
    (r"A\times B", True),
    (r"\mathbf{A}\cdot\mathbf{B}", True),
])
async def test_runtime_preserves_symbolic_matrix_product(
    tmp_path, candidate_first, candidate, should_commit,
):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first), model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run(
        "两个未给具体元素的二乘二矩阵 A 与 B，写出 A 乘 B 的符号乘积"
    )

    assert result.committed is should_commit
    assert result.latex == candidate
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"
        assert result.formula_ledger["commits"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.parametrize("candidate,should_commit", [
    (r"n^{\text{阶}}", False),
    ("n!", True),
    (r"\left(n\right)!", True),
])
async def test_runtime_preserves_unevaluated_factorial(
    tmp_path, candidate_first, candidate, should_commit,
):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first), model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("n 的阶乘")

    assert result.committed is should_commit
    assert result.latex == candidate
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"
        assert result.formula_ledger["commits"] == []


@pytest.mark.asyncio
async def test_runtime_passes_intact_factorial_pretranslation_to_planner(tmp_path):
    candidate = "n!"
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=False), model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("n 的阶乘")

    assert result.valid
    assert result.committed
    prompt = planner.seen_messages[0][1]["content"]
    assert "n 的阶乘" in prompt  # The original request remains available.
    assert "n 的!" in prompt
    assert r"阶\times" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_first", [False, True])
@pytest.mark.parametrize("candidate,should_commit", [
    (r"\lim_{n \to \infty} a_{n=L}", False),
    (r"\lim_{n\to\infty}a_n=L", True),
    (r"a_n\xrightarrow{n\to\infty}L", True),
    (r"a_n\to L", True),
])
async def test_runtime_preserves_sequence_limit_statement(
    tmp_path, candidate_first, candidate, should_commit,
):
    planner = FakePlanner([PlannerTurn(content=candidate)] * 8)
    planner.generate_latex = AsyncMock(return_value=candidate)
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(data_dir=tmp_path, nl_candidate_first=candidate_first), model=planner,
    )
    disable_deterministic_candidates(runtime)
    runtime.backend.ensure_ready = AsyncMock(return_value=True)

    result = await runtime.run("n 趋近于无穷时数列 a 下标 n 等于 L")

    assert result.committed is should_commit
    assert result.latex == candidate
    if should_commit:
        assert result.valid
    else:
        assert result.stop_reason == "semantic_anchor_unresolved"
        assert result.formula_ledger["commits"] == []
