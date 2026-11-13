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


def test_fix_mismatched_matrix_environment_prefers_decorated_pair():
    fixer = LaTeXFixer()
    result = fixer.fix(
        r"\begin{matrix}a&b\\c&d\end{pmatrix}",
        [CheckResult(ok=False, type="env_unbalanced", detail="mismatch")],
    )

    assert result.fixed
    assert result.latex == r"\begin{pmatrix}a&b\\c&d\end{pmatrix}"


def test_fix_mismatched_environment_keeps_opening_environment():
    fixer = LaTeXFixer()
    result = fixer.fix(
        r"\begin{pmatrix}a&b\\c&d\end{bmatrix}",
        [CheckResult(ok=False, type="env_unbalanced", detail="mismatch")],
    )

    assert result.fixed
    assert result.latex == r"\begin{pmatrix}a&b\\c&d\end{pmatrix}"


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


# ── KaTeX 时代的命令/环境修复（issue #77）──────────────────────────────
# validator 改用 KaTeX 后只产出 katex_parse，旧的 unknown_command 分支不再触发。

KATEX_ERRORS = {
    "fr": (r"y=(x+2)e^\fr1 x",
           r"KaTeX parse error: Undefined control sequence: \fr at position 11: ..."),
    "bet": (r"\alpha + \bet",
            r"KaTeX parse error: Undefined control sequence: \bet at position 11: ..."),
    "env": (r"\begin{case}fx",
            r"KaTeX parse error: No such environment: case at position 7: ..."),
}


def test_fix_truncated_command_from_katex_error():
    latex, message = KATEX_ERRORS["fr"]
    result = LaTeXFixer().fix(latex, [CheckResult(ok=False, type="katex_parse", error=message)])
    assert result.fixed
    assert result.latex == r"y=(x+2)e^\frac1 x"
    assert "\\frac" in result.log[0]


def test_fix_truncated_command_keeps_longer_valid_command():
    # \frac 已经是对的，不能因为 \fr 的映射把它改成 \fracrac
    result = LaTeXFixer().fix(
        r"\frac{a}{b}+\fr{c}{d}",
        [
            CheckResult(
                ok=False,
                type="katex_parse",
                error=r"KaTeX parse error: Undefined control sequence: \fr at position 13: ...",
            )
        ],
    )
    assert result.latex == r"\frac{a}{b}+\frac{c}{d}"


def test_fix_greek_truncation():
    latex, message = KATEX_ERRORS["bet"]
    result = LaTeXFixer().fix(latex, [CheckResult(ok=False, type="katex_parse", error=message)])
    assert result.latex == r"\alpha + \beta"


def test_fix_unknown_environment_prefix():
    latex, message = KATEX_ERRORS["env"]
    result = LaTeXFixer().fix(latex, [CheckResult(ok=False, type="katex_parse", error=message)])
    assert result.fixed
    assert result.latex.startswith(r"\begin{cases}")
    assert "cases" in result.log[0]


def test_unknown_environment_without_unique_prefix_is_left_alone():
    result = LaTeXFixer().fix(
        r"\begin{al}x\end{al}",
        [CheckResult(ok=False, type="katex_parse",
                     error="KaTeX parse error: No such environment: al at position 7: ...")],
    )
    # al 同时是 aligned/alignedat/align/alignat 的前缀 → 不唯一，拒绝猜测
    assert not result.fixed
    assert result.latex == r"\begin{al}x\end{al}"


def test_unrelated_katex_error_is_not_touched():
    result = LaTeXFixer().fix(
        r"\frac{a}{b",
        [CheckResult(ok=False, type="katex_parse",
                     error="KaTeX parse error: Expected '}', got 'EOF' at end of input")],
    )
    assert not result.fixed
