"""Test LaTeXValidator — multi-layer syntax checking."""
from texada.core.validator import LaTeXValidator


def test_valid_simple():
    v = LaTeXValidator()
    r = v.validate("\\frac{a}{b}")
    assert r.valid


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