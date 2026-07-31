"""Deterministic candidate extraction regression tests."""

import pytest

from texada.core.candidates import DeterministicCandidateEngine


def test_range_sum_without_explicit_qiuhe_is_structured():
    candidate = DeterministicCandidateEngine().propose("求k从1到n的k平方")

    assert candidate is not None
    assert candidate.rule == "nl_range_sum"
    assert candidate.latex == r"\sum_{k=1}^{n} k^2"


def test_spaced_range_sum_is_structured():
    candidate = DeterministicCandidateEngine().propose(
        "求和 k 从 1 到 n 的 k 平方"
    )

    assert candidate is not None
    assert candidate.latex == r"\sum_{k=1}^{n} k^2"


def test_range_sum_without_leading_request_verb_is_structured():
    candidate = DeterministicCandidateEngine().propose("k从1到n的k平方之和")

    assert candidate is not None
    assert candidate.latex == r"\sum_{k=1}^{n} k^2"


def test_inline_bare_sum_command_is_restored():
    candidate = DeterministicCandidateEngine().propose(
        "求k从1到n的k平方 sum_{k=1}^{n} k^2"
    )

    assert candidate is not None
    assert candidate.rule == "inline_latex_hint"
    assert candidate.latex == r"\sum_{k=1}^{n} k^2"


def test_unstructured_natural_language_still_uses_planner():
    candidate = DeterministicCandidateEngine().propose("请帮我解释平方和的含义")

    assert candidate is None


def test_partial_derivative_keeps_the_expression():
    candidate = DeterministicCandidateEngine().propose("偏导 u 关于 x")

    assert candidate is not None
    assert candidate.rule == "nl_partial_derivative"
    assert candidate.latex == r"\frac{\partial u}{\partial x}"


def test_suffix_partial_derivative_form_is_supported():
    candidate = DeterministicCandidateEngine().propose("u 对 x 的偏导数")

    assert candidate is not None
    assert candidate.latex == r"\frac{\partial u}{\partial x}"


def test_partial_derivative_accepts_function_call_expression():
    candidate = DeterministicCandidateEngine().propose(
        "偏导 f(x, y) 关于 x"
    )

    assert candidate is not None
    assert candidate.latex == r"\frac{\partial f(x,y)}{\partial x}"


def test_standard_quotient_limit_is_structured():
    candidate = DeterministicCandidateEngine().propose(
        "x趋向0时 sin x 除以 x 的极限"
    )

    assert candidate is not None
    assert candidate.rule == "nl_quotient_limit"
    assert candidate.latex == r"\lim_{x\to 0} \frac{\sin x}{x}"


def test_quotient_limit_accepts_dang_and_tends_to_synonym():
    candidate = DeterministicCandidateEngine().propose(
        "当x趋近于0时 sin x 除以 x 的极限"
    )

    assert candidate is not None
    assert candidate.latex == r"\lim_{x\to 0} \frac{\sin x}{x}"


def test_multiple_integral_keeps_domain_and_differentials():
    candidate = DeterministicCandidateEngine().propose(
        "二重积分 f(x,y) 在区域 D 上"
    )

    assert candidate is not None
    assert candidate.rule == "nl_multiple_integral"
    assert candidate.latex == r"\iint_{D} f(x,y)\,dx\,dy"


def test_simple_division_uses_a_fraction():
    candidate = DeterministicCandidateEngine().propose("a除以b")

    assert candidate is not None
    assert candidate.rule == "nl_simple_division"
    assert candidate.latex == r"\frac{a}{b}"


def test_simple_equality_is_zero_model_safe():
    candidate = DeterministicCandidateEngine().propose("2乘3等于6")

    assert candidate is not None
    assert candidate.rule == "nl_simple_equality"
    assert candidate.latex == r"2\times 3=6"


def test_simple_equality_accepts_natural_operator_suffixes():
    engine = DeterministicCandidateEngine()

    assert engine.propose("2加上3等于5").latex == "2+3=5"
    assert engine.propose("2乘以3等于6").latex == r"2\times 3=6"


def test_sum_power_preserves_grouping():
    candidate = DeterministicCandidateEngine().propose("x与y之和的平方")

    assert candidate is not None
    assert candidate.rule == "nl_sum_power"
    assert candidate.latex == "(x+y)^2"


def test_radical_scopes_the_full_following_expression():
    candidate = DeterministicCandidateEngine().propose("根号下 x 加 1")

    assert candidate is not None
    assert candidate.rule == "nl_simple_radical"
    assert candidate.latex == r"\sqrt{x+1}"


def test_structured_nl_ignores_sentence_ending_punctuation():
    engine = DeterministicCandidateEngine()

    assert engine.propose("求k从1到n的k平方。").latex == (
        r"\sum_{k=1}^{n} k^2"
    )
    assert engine.propose("二重积分 f(x,y) 在区域 D 上！").latex == (
        r"\iint_{D} f(x,y)\,dx\,dy"
    )
    assert engine.propose("a除以b？").latex == r"\frac{a}{b}"


def test_radical_accepts_natural_operator_suffix():
    candidate = DeterministicCandidateEngine().propose("根号下 x 加上 1")

    assert candidate is not None
    assert candidate.latex == r"\sqrt{x+1}"


@pytest.mark.parametrize(
    ("text", "required"),
    [
        ("dot product(v,m)", (r"\cdot", "v", "m")),
        ("inner product", (r"\langle", r"\rangle")),
        ("向量 u 与 v 的内积", (r"\langle", r"\rangle", "u", "v")),
        ("二重积分", (r"\iint", r"\placeholder")),
        ("double integral", (r"\iint", r"\placeholder")),
        ("三重积分", (r"\iiint", r"\placeholder")),
        ("triple integral", (r"\iiint", r"\placeholder")),
        ("分段函数", (r"\begin{cases}", r"\placeholder")),
        ("piecewise function", (r"\begin{cases}", r"\placeholder")),
        ("导数定义", (r"\lim", r"\frac")),
        ("导数的极限定义式", (r"\lim", r"\frac")),
        ("极限定义式", (r"\lim",)),
        ("概率密度函数", ("f_X", r"\int")),
        ("probability density function", ("f_X", r"\int")),
        ("probability denisity function", ("f_X", r"\int")),
        ("连续随机变量", ("X", r"\int")),
        ("交叉熵损失", (r"\sum", r"\log")),
        ("信息熵公式", ("H", r"\log")),
        ("实数域 R", (r"\mathbb{R}",)),
        ("贝叶斯公式", ("P", r"\frac")),
    ],
)
def test_named_math_concepts_have_canonical_zero_model_candidates(text, required):
    candidate = DeterministicCandidateEngine().propose(text)

    assert candidate is not None
    assert candidate.rule == "nl_canonical_concept"
    assert all(fragment in candidate.latex for fragment in required)
