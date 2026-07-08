"""Test LaTeXValidator — multi-layer syntax checking."""
import subprocess

from texada.core.validator import LaTeXValidator


def test_valid_simple():
    v = LaTeXValidator()
    r = v.validate("\\frac{a}{b}")
    assert r.valid


def test_missing_local_katex_cli_is_skipped(monkeypatch):
    def missing_local_katex(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr=(
                "npm error npx canceled due to missing packages "
                'and no YES option: ["katex@0.17.0"]'
            ),
        )

    monkeypatch.setattr("texada.core.validator.subprocess.run", missing_local_katex)

    v = LaTeXValidator()
    r = v.validate("\\frac{a}{b}")

    assert r.valid
    assert not r.errors


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
