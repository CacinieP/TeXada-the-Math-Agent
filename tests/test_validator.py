"""Test LaTeXValidator — multi-layer syntax checking."""

from texada.core.validator import LaTeXValidator


def test_valid_simple():
    v = LaTeXValidator()
    r = v.validate("\\frac{a}{b}")
    assert r.valid


def test_valid_long_katex_command_is_not_blocked_by_a_hand_whitelist():
    v = LaTeXValidator()
    r = v.validate(r"\xrightarrow{n\to\infty}x")

    assert r.valid
    assert not r.errors


def test_undefined_command_is_rejected_by_vendored_katex():
    v = LaTeXValidator()
    r = v.validate(r"\definitelyUnknownCommand{x}")

    assert not r.valid
    assert any(e.type == "katex_parse" for e in r.errors)


def test_brace_unbalanced_missing():
    v = LaTeXValidator()
    r = v.validate("A^{-1 = \\frac{1}{\\det(A)}")
    assert not r.valid
    assert any(e.type == "brace_unbalanced" for e in r.errors)


def test_brace_unbalanced_extra():
    v = LaTeXValidator()
    r = v.validate("{}}")
    assert not r.valid


def test_env_unbalanced():
    v = LaTeXValidator()
    r = v.validate("\\begin{bmatrix} a & b")
    assert not r.valid
    assert any(e.type == "env_unbalanced" for e in r.errors)


def test_environment_names_must_match_and_extra_end_is_rejected():
    validator = LaTeXValidator()

    for value in [
        r"\begin{pmatrix}a\end{bmatrix}",
        r"\end{align*}",
    ]:
        result = validator.validate(value)
        assert not result.valid
        assert any(error.type == "env_unbalanced" for error in result.errors)


def test_brace_balanced():
    v = LaTeXValidator()
    r = v.validate("\\int_0^1 f(x) dx")
    assert r.valid


def test_command_with_subscript_not_swallowed():
    """Command regex must not treat `_` as part of the command name.

    Regression: `\\w` included `_`, so `\\partial_i` was read as the command
    "partial_i" and flagged as unknown. LaTeX command names are letters only.
    """
    v = LaTeXValidator()
    for latex in [r"\partial_i", r"\sum_{i=1}^{n}", r"\int_0^1", r"\alpha_n"]:
        r = v.validate(latex)
        assert r.valid, f"{latex!r} should be valid, got errors: {r.errors}"
        assert not any(e.type == "unknown_command" for e in r.errors)


def test_prose_is_not_accepted_as_a_formula():
    v = LaTeXValidator()

    for value in ["这是一个公式", "This is a helpful explanation"]:
        result = v.validate(value)
        assert not result.valid
        assert any(e.type == "non_formula_content" for e in result.errors)


def test_explicit_text_command_can_contain_chinese():
    assert LaTeXValidator().validate(r"\text{中文} + x").valid


def test_semantically_empty_structures_are_rejected():
    v = LaTeXValidator()

    for value in [r"\frac{x}{}", r"\frac{}{y}", r"\sqrt{}", r"x_{}", r"x^{}"]:
        assert not v.validate(value).valid


def test_placeholder_is_a_supported_local_macro():
    v = LaTeXValidator()

    assert v.validate(r"\frac{\placeholder{}}{\placeholder{}}").valid
    assert v.validate(r"\sqrt{\placeholder{}}").valid


def test_ellipsis_and_markup_are_not_formula_content():
    validator = LaTeXValidator()

    for value in ["...", "…", r"\cdots", "x^]><![CDATA[<b>2</b>"]:
        result = validator.validate(value)
        assert not result.valid
        assert any(error.type == "non_formula_content" for error in result.errors)
