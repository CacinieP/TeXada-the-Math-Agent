"""Test LaTeX Syntax Highlighter."""
from texada.render.highlighter import LaTeXHighlighter


def test_simple_frac():
    h = LaTeXHighlighter()
    result = h.highlight("\\frac{a}{b}")
    assert "latex-frac" in result
    assert "\\frac" in result


def test_integral():
    h = LaTeXHighlighter()
    result = h.highlight("\\int_0^1 f(x) dx")
    assert "latex-structural" in result
    assert "latex-delimiter" in result


def test_delimiters():
    h = LaTeXHighlighter()
    result = h.highlight("{x^2}")
    assert "latex-delimiter" in result
    assert "latex-operator" in result


def test_no_escaping_issue():
    h = LaTeXHighlighter()
    result = h.highlight("\\frac{\\partial u}{\\partial v}")
    # Should not double-escape HTML
    assert "&amp;" not in result