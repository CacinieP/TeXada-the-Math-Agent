"""Finite transcription constraints and v0.4.3 source counterexamples."""
from __future__ import annotations

import pytest

from texada.core.transcription import check_transcription, recognize_transcription
from texada.core.validator import LaTeXValidator

# Minimal formula excerpts from the official v0.4.3 replay on 2026-11-06.
# Release source 6adcba0ab1540f2efb1bf78156783842001bc72c, replay export SHA-256
# c23b8862b2b23fd99c0cb0a395fb00c781391bbcbba2ee058fae2d205d67202c.
# Each parameter retains its case and replay run ID for traceability.
RELEASE_FAILURES = [
    pytest.param(
        "写一个求和公式，对bn求和",
        r"\sum_{n=1}^{\infty} b_n \sum_{k=1}^{\infty} a_k",
        id="C05-06547e53bc814b419d13cde5876015ab",
    ),
    pytest.param(
        "写一个求和公式，其中每一项是函数Fi在omega_i上的积分",
        r"\sum_{i=1}^n \int_{\omega_i}^{omega_{i+1}} Fi(x)\,dx",
        id="C09-a35e889115054bf3891d3c8ab63c72d9",
    ),
    pytest.param(
        "对F(x)进行求和，其中x取遍整数中的元素",
        r"\sum_{x=1}^{n} F(x)",
        id="C14-b97282caf0634c31b341534cd354099e",
    ),
]


@pytest.mark.parametrize("source,failed_latex", RELEASE_FAILURES)
def test_official_release_syntax_success_does_not_prove_source_fidelity(source, failed_latex):
    spec = recognize_transcription(source)
    assert spec is not None
    assert LaTeXValidator().validate(failed_latex).valid
    evidence = check_transcription(spec, failed_latex)
    assert evidence["verdict"] == "DIFFERENT"
    assert evidence["candidate_tree_sha256"] != evidence["expected_tree_sha256"]
    assert LaTeXValidator().validate(spec.latex).valid
    assert check_transcription(spec, spec.latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("term", ["bn", "b_n", "b_{n}"])
@pytest.mark.parametrize("prefix", ["", "写一个求和公式，", "写出一个求和公式, "])
def test_indexed_sum_keeps_its_only_term_without_inventing_bounds(term, prefix):
    spec = recognize_transcription(f"{prefix}对{term}求和。")
    assert spec is not None
    assert spec.latex == r"\sum_{n} b_n"
    assert spec.unspecified_fields == ("sum_bounds",)
    assert spec.rule == "nl_indexed_sum"


@pytest.mark.parametrize("domain,expected", [
    ("整数", r"\mathbb{Z}"), ("整数集", r"\mathbb{Z}"),
    ("A", "A"), ("集合A", "A"), ("集合 B", "B"),
])
def test_function_domain_preserves_explicit_set(domain, expected):
    spec = recognize_transcription(f"对F(x)进行求和，其中x取遍{domain}中的元素")
    assert spec is not None
    assert spec.latex == rf"\sum_{{x \in {expected}}} F(x)"
    assert check_transcription(spec, spec.latex)["verdict"] == "MATCH"


def test_function_and_index_case_are_preserved():
    spec = recognize_transcription("对f(X)进行求和，其中X取遍a中的元素")
    assert spec is not None
    assert spec.latex == r"\sum_{X \in a} f(X)"
    assert check_transcription(spec, r"\sum_{x \in A} F(x)")["verdict"] == "DIFFERENT"


@pytest.mark.parametrize("function", ["Fi", "F_i", "F_{i}"])
@pytest.mark.parametrize("region", ["omegai", "omega_i", "omega_{i}", r"\omega_i", "ω_i"])
def test_region_sum_keeps_function_index_region_and_implicit_measure(function, region):
    spec = recognize_transcription(f"写一个求和公式，其中每一项是函数{function}在{region}上的积分")
    assert spec is not None
    assert spec.latex == r"\sum_{i} \int_{\omega_i} F_i"
    assert spec.unspecified_fields == ("sum_bounds", "integration_measure")
    assert not spec.clarification
    assert check_transcription(spec, spec.latex)["verdict"] == "MATCH"


def test_uppercase_region_and_arbitrary_single_index_are_preserved():
    spec = recognize_transcription("写一个求和公式，其中每一项是函数Gk在Omega_k上的积分")
    assert spec is not None
    assert spec.latex == r"\sum_{k} \int_{\Omega_k} G_k"
    assert check_transcription(spec, spec.latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("source", [
    "写一个求和公式，其中每一项是函数Fi在omega_上的积分",
    "写一个求和公式，其中每一项是函数Fi在omega上的积分",
    "写一个求和公式，其中每一项是函数Fi在omega_j上的积分",
    "对F(x)进行求和，其中y取遍整数中的元素",
])
def test_incomplete_or_conflicting_roles_require_clarification(source):
    spec = recognize_transcription(source)
    assert spec is not None
    assert spec.latex == ""
    assert spec.clarification
    evidence = check_transcription(spec, r"\sum_{i=1}^n \int_{\omega_i} F_i\,dx")
    assert evidence["verdict"] == "NOT_CHECKED"
    assert evidence["diagnostics"] == [spec.clarification]


@pytest.mark.parametrize("source", [
    "写一个求和公式，对bn求和，其中n从1到10",
    "写一个求和公式，对bn求和，然后化简",
    "写一个求和公式，对bn求和，且bn等于0.5",
    "写一个求和公式，其中每一项是函数Fi在omega_i上的积分，积分测度是dx",
    "对F(x)进行求和，其中x取遍A中的元素，并求值",
    "对F(x)进行求和，其中x取遍正整数中的元素",
    "写一个求和公式，对abc求和",
    "写一个求和公式，对b_{n+1}求和",
    "写一个求和公式，其中每一项是函数F_i(x)在omega_i上的积分",
    "写一个求和公式",
    "其中每一项是函数Fi在omega_i上的积分",
    "函数F在omega上的积分",
    "计算对bn求和",
    "Write a fraction whose numerator is a+b and whose denominator is 1+x squared.",
])
def test_outside_finite_grammar_does_not_discard_any_source_clause(source):
    assert recognize_transcription(source) is None


@pytest.mark.parametrize("candidate", [
    r"\sum_{n=1} b_n", r"\sum_n b_n a_n", r"\sum_n a_n", r"\sum_k b_k",
])
def test_source_check_rejects_added_bounds_factors_or_changed_symbols(candidate):
    spec = recognize_transcription("对bn求和")
    assert spec is not None
    assert check_transcription(spec, candidate)["verdict"] == "DIFFERENT"


def test_structure_check_accepts_bracing_and_presentation_spacing():
    spec = recognize_transcription("对bn求和")
    assert spec is not None
    assert check_transcription(spec, r"\displaystyle\sum_n\,b_{n}")["verdict"] == "MATCH"


@pytest.mark.parametrize("candidate", [r"\unknown{x}", r"\text{a sum}", r"\def\x{b}\sum_n\x_n"])
def test_unavailable_or_unsupported_structure_never_reports_match(candidate):
    spec = recognize_transcription("对bn求和")
    assert spec is not None
    assert check_transcription(spec, candidate)["verdict"] == "UNSUPPORTED"


def test_missing_candidate_is_not_checked():
    spec = recognize_transcription("对bn求和")
    assert spec is not None
    assert check_transcription(spec, "")["verdict"] == "NOT_CHECKED"


@pytest.mark.parametrize("name", ["ln", "pi", "Pi", "mu", "nu", "xi", "Xi"])
def test_ambiguous_joined_names_require_explicit_index(name):
    for source in (
        f"对{name}求和",
        f"写一个求和公式，其中每一项是函数{name}在omega_{name[-1]}上的积分",
    ):
        spec = recognize_transcription(source)
        assert spec is not None and spec.clarification and spec.latex == ""
    explicit = recognize_transcription(f"对{name[0]}_{name[1]}求和")
    assert explicit is not None and not explicit.clarification
    assert explicit.latex == rf"\sum_{{{name[1]}}} {name[0]}_{name[1]}"
