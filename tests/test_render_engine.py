"""Test RenderEngine — dual mode switching."""
import subprocess

from texada.config import TeXadaConfig
from texada.render.engine import RenderEngine
from texada.types import RenderMode


def test_katex_mode():
    config = TeXadaConfig(default_render_mode="katex")
    engine = RenderEngine(config)
    result = engine.render("\\frac{a}{b}")
    assert result.mode == RenderMode.KATEX
    assert result.copy_text == "$$\\frac{a}{b}$$"


def test_katex_uses_local_npx_without_install(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='<span class="katex">ok</span>',
            stderr="",
        )

    monkeypatch.setattr("texada.render.engine.subprocess.run", fake_run)

    config = TeXadaConfig(default_render_mode="katex")
    engine = RenderEngine(config)
    result = engine.render("\\frac{a}{b}")

    assert captured["cmd"] == ["npx", "--no-install", "katex"]
    assert result.katex_html == '<span class="katex">ok</span>'


def test_katex_fallback_is_visible_without_npx(monkeypatch):
    def missing_npx(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("texada.render.engine.subprocess.run", missing_npx)

    config = TeXadaConfig(default_render_mode="katex")
    engine = RenderEngine(config)
    result = engine.render("\\frac{a}{b}")

    assert "npx katex not available" not in result.katex_html
    assert "katex-fallback" in result.katex_html
    assert "\\frac{a}{b}" in result.katex_html
    assert result.copy_text == "$$\\frac{a}{b}$$"


def test_latex_mode():
    config = TeXadaConfig(default_render_mode="latex")
    engine = RenderEngine(config)
    result = engine.render("\\frac{a}{b}")
    assert result.mode == RenderMode.LATEX
    assert result.copy_text == "\\frac{a}{b}"
    assert result.latex_highlighted is not None


def test_switch_mode():
    config = TeXadaConfig(default_render_mode="katex")
    engine = RenderEngine(config)
    # Initial render in katex
    engine.render("\\int_0^1 f(x) dx")
    # Switch to latex mode — zero model call
    result = engine.switch_mode("latex")
    assert result.mode == RenderMode.LATEX
    assert result.copy_text == "\\int_0^1 f(x) dx"
    assert result.latex_highlighted is not None


def test_switch_back():
    config = TeXadaConfig(default_render_mode="latex")
    engine = RenderEngine(config)
    engine.render("\\sum x_i")
    result = engine.switch_mode("katex")
    assert result.mode == RenderMode.KATEX
    assert result.copy_text == "$$\\sum x_i$$"


def test_delimiter_bracket():
    config = TeXadaConfig(default_render_mode="katex", delimiter="\\[")
    engine = RenderEngine(config)
    result = engine.render("x^2")
    # delimiter="\\[" means open=\\[ close=\\]
    assert result.copy_text == "\\[x^2\\]"
