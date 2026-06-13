"""Test InputRouter — routing, rendering, and pipeline dispatch."""
import pytest
from unittest.mock import AsyncMock, patch
from texada.config import TeXadaConfig
from texada.core.router import InputRouter
from texada.types import Tab, Route, RenderResult, RenderMode, ToolCall, ToolResult


def test_router_routing():
    config = TeXadaConfig()
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
    result = router._render("\\frac{a}{b}")
    assert isinstance(result, RenderResult)
    assert result.latex == "\\frac{a}{b}"
    assert result.mode == RenderMode.KATEX


@pytest.mark.asyncio
async def test_router_process_text_shorthand():
    config = TeXadaConfig()
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
