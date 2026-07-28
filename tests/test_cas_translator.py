"""Whitelist Semantic Unit to SymPy translation tests."""

import pytest

from texada.cas import CASTranslationError, SemanticSymPyTranslator
from texada.semantic import SemanticParser

pytest.importorskip("sympy")


@pytest.fixture(scope="module")
def parser():
    return SemanticParser()


@pytest.mark.parametrize(
    ("latex", "expected_srepr"),
    [
        ("2+3*4", "Integer(14)"),
        (
            r"\frac{x+1}{2}",
            "Add(Mul(Rational(1, 2), Symbol('x')), Rational(1, 2))",
        ),
        (
            "x^2+2x+1",
            "Add(Pow(Symbol('x'), Integer(2)), Mul(Integer(2), Symbol('x')), Integer(1))",
        ),
        (r"\sqrt[3]{8}", "Integer(2)"),
        (
            r"\sin(x)+\cos x",
            "Add(sin(Symbol('x')), cos(Symbol('x')))",
        ),
        (
            r"\sin(x)^2+\cos(x)^2",
            "Add(Pow(sin(Symbol('x')), Integer(2)), "
            "Pow(cos(Symbol('x')), Integer(2)))",
        ),
        (
            r"\int_0^1 x^2\,dx",
            "Integral(Pow(Symbol('x'), Integer(2)), "
            "Tuple(Symbol('x'), Integer(0), Integer(1)))",
        ),
    ],
)
def test_translator_accepts_only_declared_scalar_subset(parser, latex, expected_srepr):
    translated = SemanticSymPyTranslator().translate_document(parser.parse(latex))

    assert translated.srepr == expected_srepr


@pytest.mark.parametrize(
    ("latex", "reason_code"),
    [
        (r"\hat{H}", "unsupported_command"),
        (r"\bar{x}", "unsupported_command"),
        (r"\vec{x}", "unsupported_command"),
        (r"\operatorname{Var}(X)", "unsupported_katex_node"),
        (r"e^{i\pi}+1", "ambiguous_constant_symbol"),
        (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}", "structured_environment"),
        (r"\sum_{k=1}^{5}k", "unsupported_operator"),
        (r"\int x\,dx", "unbounded_integral"),
    ],
)
def test_translator_rejects_known_silent_drift_and_structural_notation(
    parser,
    latex,
    reason_code,
):
    with pytest.raises(CASTranslationError) as captured:
        SemanticSymPyTranslator().translate_document(parser.parse(latex))

    assert captured.value.failure.code == reason_code


def test_translator_records_explicit_symbol_assumptions(parser):
    translator = SemanticSymPyTranslator(
        assumptions={"x": {"real": True, "nonnegative": True}}
    )

    translated = translator.translate_document(parser.parse(r"\sqrt{x^2}"))

    assert translated.expression.is_real is True
    assert translated.expression.is_nonnegative is True
    assert translator.assumption_labels == ["x is nonnegative", "x is real"]


def test_fallback_parser_is_never_a_cas_authority():
    document = SemanticParser(use_katex=False).parse("x+1")

    with pytest.raises(CASTranslationError) as captured:
        SemanticSymPyTranslator().translate_document(document)

    assert captured.value.failure.code == "untrusted_parser_backend"
