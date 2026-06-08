"""Test LaTeXFixer — auto-repair without model."""
from texada.core.fixer import LaTeXFixer
from texada.types import CheckResult


def test_fix_missing_braces():
    f = LaTeXFixer()
    result = f.fix("A^{-1 = \\frac{1}{\\det(A)}", [
        CheckResult(ok=False, type="brace_unbalanced", detail="missing 1 }")
    ])
    assert result.fixed
    assert result.latex.endswith("}")
    assert "补全" in result.log[0]


def test_fix_missing_end():
    f = LaTeXFixer()
    result = f.fix("\\begin{bmatrix} a & b", [
        CheckResult(ok=False, type="env_unbalanced", detail="missing \\end{bmatrix}")
    ])
    assert result.fixed
    assert "\\end{bmatrix}" in result.latex


def test_fix_command_replace():
    f = LaTeXFixer()
    result = f.fix("\\begin{array} x \\end{array}", [
        CheckResult(ok=False, type="unknown_command", detail="可疑命令: array")
    ])
    assert result.fixed
    assert "\\begin{aligned}" in result.latex


def test_no_fix_needed():
    f = LaTeXFixer()
    result = f.fix("\\frac{a}{b}", [])
    assert not result.fixed
    assert result.latex == "\\frac{a}{b}"