"""Test InputRouter — routing, rendering, and pipeline dispatch."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from texada.config import TeXadaConfig
from texada.core.router import InputRouter
from texada.types import RenderMode, RenderResult, Route, Tab


def test_router_routing(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    router = InputRouter(config)

    # 1. OCR tab always routes to OCR
    assert router.route(Tab.OCR, b"image_data") == Route.OCR

    # 2. Shorthand tab always routes to Shorthand
    assert router.route(Tab.SHORTHAND, "key") == Route.SHORTHAND

    # 3. Completion tab always routes to Completion
    assert router.route(Tab.COMPLETION, "\\int") == Route.COMPLETION

    # 4. NL tab - auto-detect shorthand
    # Add a temporary shorthand to test
    router.shorthand_store.add("temp_key", "x^2")
    assert router.route(Tab.NL, "temp_key") == Route.SHORTHAND

    # 5. NL tab - auto-detect completion (contains backslash command)
    assert router.route(Tab.NL, "\\frac{a}{b}") == Route.COMPLETION

    # 6. NL tab - default to NL2LATEX
    assert router.route(Tab.NL, "f(x) from 0 to 1") == Route.NL2LATEX


def test_router_render_no_recursion():
    config = TeXadaConfig()
    router = InputRouter(config)

    # Calling _render should not cause infinite recursion
    result = router._render("\\frac{a}{b}", None)
    assert isinstance(result, RenderResult)
    assert result.latex == "\\frac{a}{b}"
    assert result.mode == RenderMode.KATEX


@pytest.mark.asyncio
async def test_router_process_text_shorthand(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    router = InputRouter(config)
    router.shorthand_store.add("t_shorthand", "x_i^2")

    result = await router.process_text("t_shorthand")
    assert result.latex == "x_i^2"
    assert result.valid
    assert result.intent == "shorthand"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_router_process_text_nl2latex_mocked():
    config = TeXadaConfig()
    router = InputRouter(config)

    # Mock the model call to avoid needing Ollama service during tests
    mock_generate = AsyncMock(return_value="\\int_0^1 f(x) dx")
    router.model.generate_latex = mock_generate

    # Mock backend ensure_ready to return True
    mock_ready = AsyncMock(return_value=True)
    router.backend.ensure_ready = mock_ready

    result = await router.process_text("f(x)的积分从0到1", route_override=Route.NL2LATEX)
    assert result.latex == "\\int_0^1 f(x) dx"
    assert result.valid
    assert result.intent == "integral"
    mock_generate.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_render_modes_do_not_leak(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    router = InputRouter(config)

    async def fake_generate(preprocessed, intent, memory_messages=None, force_operators=None):
        if "slow" in preprocessed:
            await asyncio.sleep(0.05)
        return "x+1"

    router.model.generate_latex = fake_generate
    router.backend.ensure_ready = AsyncMock(return_value=True)

    katex_task = asyncio.create_task(
        router.process_text(
            "slow request",
            route_override=Route.NL2LATEX,
            render_mode=RenderMode.KATEX,
        )
    )
    await asyncio.sleep(0.01)
    latex_task = asyncio.create_task(
        router.process_text(
            "fast request",
            route_override=Route.NL2LATEX,
            render_mode=RenderMode.LATEX,
        )
    )

    katex_result, latex_result = await asyncio.gather(katex_task, latex_task)

    assert katex_result.render.mode == RenderMode.KATEX
    assert katex_result.render.katex_html is not None
    assert katex_result.render.latex_highlighted is None
    assert latex_result.render.mode == RenderMode.LATEX
    assert latex_result.render.katex_html is None
    assert latex_result.render.latex_highlighted is not None


@pytest.mark.asyncio
async def test_nl_conversion_does_not_reuse_previous_memory(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    router = InputRouter(config)
    seen_memory_lengths = []

    async def fake_generate(preprocessed, intent, memory_messages=None, force_operators=None):
        seen_memory_lengths.append(len(memory_messages or []))
        return "x+1" if "first" in preprocessed else "y+1"

    router.model.generate_latex = fake_generate
    router.backend.ensure_ready = AsyncMock(return_value=True)

    first = await router.process_text("first request", route_override=Route.NL2LATEX)
    second = await router.process_text("second request", route_override=Route.NL2LATEX)

    assert first.latex == "x+1"
    assert second.latex == "y+1"
    assert seen_memory_lengths == [0, 0]


@pytest.mark.asyncio
async def test_rule_completion_works_without_a_running_backend(tmp_path):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(side_effect=AssertionError("must not run"))

    result = await router.process_text(
        r"\frac{",
        route_override=Route.COMPLETION,
    )

    assert result.latex == r"\frac{\placeholder{}}{\placeholder{}}"
    assert result.valid is True
    assert result.tokens_used == 0
    router.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        (r"x+\alp", r"x+\alpha"),
        (r"\frac{a}{b}", r"\frac{a}{b}"),
        (r"\frac{a}{b", r"\frac{a}{b}"),
        ("a_", r"a_{\placeholder{}}"),
        ("x^", r"x^{\placeholder{}}"),
        (r"\int_0^", r"\int_0^{\placeholder{}}"),
        (r"\frac{}{b}", r"\frac{\placeholder{}}{b}"),
        (r"\sum_{i=1}^{} x_i", r"\sum_{i=1}^{\placeholder{}} x_i"),
        (r"x+\alxha", r"x+\alpha"),
        (r"\frax{a}{b}", r"\frac{a}{b}"),
        (
            r"\begin{matrix}a&b\\c&d\end{pmatrix}",
            r"\begin{pmatrix}a&b\\c&d\end{pmatrix}",
        ),
    ],
)
async def test_deterministic_completion_candidates_skip_generation(
    tmp_path,
    partial,
    expected,
):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(
        side_effect=AssertionError("must not run")
    )
    router.model.complete_latex = AsyncMock(
        side_effect=AssertionError("must not run")
    )

    candidate, tokens = await router.create_completion_candidate(partial)

    assert candidate == expected
    assert tokens == 0
    router.backend.ensure_ready.assert_not_awaited()
    router.model.complete_latex.assert_not_awaited()
