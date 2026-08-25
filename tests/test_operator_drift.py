"""Test operator-drift detection — guards against the small model
"answering the wrong question".

Regression: for input ``二重积分 f(x,y) 在区域 D 上`` the symbol engine
pre-translates "二重积分" → ``\\iint``, but MiniCPM5-1B was led astray by an
integral few-shot example and returned ``\\int \\sin(x)dx`` — losing the
``\\iint`` the user actually asked for. Drift detection flags this so the
router can trigger one constrained retry.
"""
from texada.config import TeXadaConfig
from texada.core.operator_guard import OperatorDriftGuard
from texada.core.router import InputRouter


def _router():
    return InputRouter(TeXadaConfig())


# ── Drift SHOULD be detected (upgrade-operator lost) ──

def test_iint_degraded_to_int_is_drift():
    r = _router()
    # preprocessed carries \iint (from "二重积分"); model returned only \int
    assert r._check_operator_drift(r"\iint f(x,y) 在区域 D 上", r"\int \sin(x) dx")


def test_iiint_degraded_to_int_is_drift():
    r = _router()
    assert r._check_operator_drift(r"\iiint f 在 V 上", r"\int f dV")


def test_iint_degraded_to_iiint_is_drift():
    # 三重 → 二重 is still a downgrade (lost one integral)
    r = _router()
    assert r._check_operator_drift(r"\iiint f", r"\iint f")


def test_sum_lost_when_expected():
    r = _router()
    # preprocessed has \sum (from "求和"); output dropped it entirely
    assert r._check_operator_drift(r"\sum x_i", r"x_1 + x_2 + x_3")


def test_prod_lost_when_expected():
    r = _router()
    assert r._check_operator_drift(r"\prod a_n", r"\sum a_n")


def test_oint_downgraded_to_int():
    r = _router()
    assert r._check_operator_drift(r"\oint_C F", r"\int_C F")


# ── Drift should NOT be flagged (no false positives) ──

def test_same_level_operator_kept():
    r = _router()
    # \int in, \int out — perfectly fine
    assert not r._check_operator_drift(r"\int f(x) dx", r"\int_0^1 f(x)\,dx")


def test_iint_kept():
    r = _router()
    # the case we actually want to FIX: \iint preserved in output
    assert not r._check_operator_drift(
        r"\iint f(x,y) 在区域 D 上", r"\iint_D f(x,y)\,dx\,dy"
    )


def test_no_operators_in_input():
    r = _router()
    # plain arithmetic in, plain arithmetic out — nothing to drift from
    assert not r._check_operator_drift("x 的平方加 y 的平方", "x^2 + y^2")


def test_operator_upgraded_is_not_drift():
    r = _router()
    # input had \int, model produced \iint — upgrading is fine, not a loss
    assert not r._check_operator_drift(r"\int f", r"\iint f")


def test_empty_output_not_drift_but_handled_elsewhere():
    # Empty output is the retry trigger the model already handles; drift
    # detection only concerns itself with non-empty wrong answers.
    r = _router()
    assert not r._check_operator_drift(r"\sum x_i", "")


def test_request_level_anchors_detect_plain_text_math_commands():
    guard = OperatorDriftGuard()
    request = "Express the tangent function applied to lowercase Greek nu."

    assert guard.check("", "tan(nu)", user_input=request)
    assert not guard.check("", r"\tan(\nu)", user_input=request)
    assert guard.missing_requirements(
        "", "tan(nu)", user_input=request
    ) == [r"\tan", r"\nu"]


def test_request_level_anchors_cover_observed_dataset_drift():
    guard = OperatorDriftGuard()
    cases = [
        ("Write the fraction with numerator a and denominator b.", "a/b"),
        ("Represent the product over j from 1 to m of g subscript j.", "jg^j"),
        ("Write an open interval between negative 3 and 5.", "-3,5"),
        ("Write that Y follows a normal distribution with mean mu.", r"\mu=0"),
        ("Write a matrix in parentheses with two rows.", "(a,b),(c,d)"),
        ("Define f piecewise with two branches.", "f(x)=x"),
    ]

    for request, candidate in cases:
        assert guard.check("", candidate, user_input=request), request


def test_sum_of_and_implicit_product_do_not_require_big_operators():
    guard = OperatorDriftGuard()

    assert not guard.check("", "u+f", user_input="Write the sum of u and f.")
    assert not guard.check(
        "",
        r"\beta w",
        user_input="Write the implicit product of lowercase beta and w.",
    )


def test_named_subscript_anchor_is_bound_to_the_requested_variable():
    guard = OperatorDriftGuard()
    request = "Express the sum over n from 0 to N of p subscript n."

    assert guard.check("", r"\sum_{n=0}^{N}p^n", user_input=request)
    assert not guard.check("", r"\sum_{n=0}^{N}p_n", user_input=request)


def test_structural_request_anchors_reject_keyword_only_matches():
    guard = OperatorDriftGuard()
    cases = [
        (
            "Write the sum of u and f.",
            r"\sum_{i=1}^{n}x_i",
            "u+f",
        ),
        (
            "A fraction has numerator exp o and denominator ln v.",
            r"\frac\exp(o)\ln(v)",
            r"\frac{\exp(o)}{\ln(v)}",
        ),
        (
            "An indefinite integral of a fraction with numerator 1 and denominator s.",
            r"\frac{1}{s}\int s\,ds",
            r"\int\frac{1}{s}\,ds",
        ),
        (
            "Write the implicit product of lowercase beta and w.",
            r"\beta\cdot w",
            r"\beta w",
        ),
        (
            "Write 1 times q using a centered dot.",
            r"\cdot 1*q",
            r"1\cdot q",
        ),
    ]

    for request, wrong, right in cases:
        assert guard.check("", wrong, user_input=request), request
        assert not guard.check("", right, user_input=request), request


def test_derivative_transpose_and_grouped_power_keep_requested_structure():
    guard = OperatorDriftGuard()
    cases = [
        (
            "Write the second derivative with respect to v of the function g of v.",
            r"\frac{df}{dx}",
            r"\frac{d^2}{dv^2}g(v)",
        ),
        (
            "Typeset the transpose of uppercase S equals a matrix in parentheses.",
            r"\text{transpose of uppercase S}=\begin{pmatrix}e\end{pmatrix}",
            r"S^{\mathsf{T}}=\begin{pmatrix}e\end{pmatrix}",
        ),
        (
            "Represent the number 5 raised to the power given by the variable t "
            "with subscript m plus 3.",
            r"5^{\sum_m t_m}+3",
            r"5^{t_m+3}",
        ),
    ]

    for request, wrong, right in cases:
        assert guard.check("", wrong, user_input=request), request
        assert not guard.check("", right, user_input=request), request


def test_guard_normalizes_ollama_escape_growth_and_repeated_integrals():
    guard = _router().operator_guard

    assert guard.normalize_candidate(r"\\int\\int_D f") == r"\iint_D f"
    assert (
        guard.normalize_candidate(r"\\int\\int\\int_V f")
        == r"\iiint_V f"
    )


def test_guard_preserves_matrix_row_separator():
    guard = _router().operator_guard
    matrix = r"\begin{matrix}a\\b\end{matrix}"

    assert guard.normalize_candidate(matrix) == matrix


def test_guard_collapses_escaped_thin_space_outside_environments():
    guard = _router().operator_guard

    assert (
        guard.normalize_candidate(r"\int_0^1 x^2 \\, dx")
        == r"\int_0^1 x^2 \,dx"
    )


def test_guard_extracts_bare_math_from_full_document():
    guard = _router().operator_guard

    result = guard.normalize_candidate(
        r"\documentclass{article}\begin{document} "
        r"\section*{Double Integral} \\int_{D} f(x,y) \, dx \, dy "
        r"\\end{document}"
    )

    assert result == r"\int_{D} f(x,y) \, dx \, dy"


def test_guard_restores_authoritative_integral_rank():
    guard = _router().operator_guard
    preprocessed = r"二重积分 \iint f(x,y)"

    result = guard.restore_required_operators(
        preprocessed,
        r"\int_D f(x,y)\,dx\,dy",
    )

    assert result == r"\iint_D f(x,y)\,dx\,dy"
    assert guard.check(preprocessed, result) is False


def test_guard_builds_narrow_fallback_when_model_returns_no_operator():
    guard = _router().operator_guard
    preprocessed = r"\iint f(x,y) 在区域 D 上"

    result = guard.restore_required_operators(preprocessed, "...")

    assert result == r"\iint_{D} f(x,y)\,dx\,dy"
    assert guard.check(preprocessed, result) is False


def test_guard_restores_domain_when_model_leaks_prose_into_valid_latex():
    guard = _router().operator_guard
    preprocessed = r"\iint f(x,y) 在区域 D 上"

    result = guard.restore_required_operators(
        preprocessed,
        r"\iint f(x,y) dx dy in region D",
    )

    assert result == r"\iint_{D} f(x,y)\,dx\,dy"


def test_guard_keeps_integral_that_already_has_the_required_domain():
    guard = _router().operator_guard
    candidate = r"\iint_D f(x,y)\,dx\,dy"

    assert (
        guard.restore_required_operators(
            r"\iint f(x,y) 在区域 D 上",
            candidate,
        )
        == candidate
    )
