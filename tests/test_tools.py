"""Independent TeX tool tests."""
import pytest

from texada.config import TeXadaConfig
from texada.tools import TeXToolset, ToolRouter


@pytest.fixture
def tool_router(tmp_path):
    return ToolRouter(TeXToolset(TeXadaConfig(data_dir=tmp_path)))


def test_tool_schemas_are_the_architecture_contract(tool_router):
    assert tool_router.names == (
        "parse_tex",
        "compile_tex",
        "repair_tex",
        "semantic_diff",
        "render_math",
        "export",
    )
    assert all(schema["type"] == "function" for schema in tool_router.schemas)


@pytest.mark.asyncio
async def test_parse_and_compile_are_independent(tool_router):
    parsed = await tool_router.execute("parse_tex", {"latex": r"\frac{a}{b}"})
    compiled = await tool_router.execute("compile_tex", {"latex": r"\frac{a}{b"})

    assert parsed.ok
    assert parsed.output["semantic_document"]["root"]["children"][0]["kind"] == "fraction"
    assert parsed.output["semantic_document"]["parser_backend"] == "katex-0.17.0-v8"
    assert compiled.ok
    assert compiled.output["valid"] is False
    assert compiled.output["diagnostics"][0]["type"] == "brace_unbalanced"


@pytest.mark.asyncio
async def test_repair_tex_uses_deterministic_rules_and_reports_semantic_diff(tool_router):
    repaired = await tool_router.execute("repair_tex", {"latex": r"\frac{a}{b"})

    assert repaired.ok
    assert repaired.output["latex"] == r"\frac{a}{b}"
    assert repaired.output["repair_method"] == "deterministic-rules"
    assert repaired.output["valid"] is True
    assert repaired.output["semantic_diff"]["change_count"] >= 1


@pytest.mark.asyncio
async def test_semantic_diff_render_and_export(tool_router):
    diff = await tool_router.execute(
        "semantic_diff",
        {"before": r"x_i", "after": r"x^i"},
    )
    rendered = await tool_router.execute(
        "render_math",
        {"latex": r"x^2", "mode": "latex"},
    )
    exported = await tool_router.execute(
        "export",
        {"latex": r"x^2", "format": "markdown"},
    )

    assert diff.ok and not diff.output["equivalent"]
    assert diff.output["algorithm"] == "role-aware-weighted-ordered-tree-edit"
    assert 0 <= diff.output["reward"] < 1
    assert rendered.ok and rendered.output["latex_highlighted"]
    assert exported.ok and exported.output["content"] == "$$\nx^2\n$$"


@pytest.mark.asyncio
async def test_tool_router_rejects_unknown_tools(tool_router):
    result = await tool_router.execute("delete_everything", {})

    assert not result.ok
    assert "Unknown tool" in result.error
