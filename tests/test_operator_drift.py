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


def test_explicit_chinese_fraction_requests_require_a_structured_fraction():
    guard = OperatorDriftGuard()
    requests = [
        "请把 a 与 b 的和除以 c 写成分式。",
        "把结果写为分式。",
        "请表示为分式。",
        "请使用分式。",
        "把结果写成分数。",
        "写为 分数形式。",
        "表示为 分数。",
        "使用 分数表示。",
        "不要化简，请把结果写成分式。",
    ]
    for request in requests:
        assert r"\frac" in guard.forced_operators("", request), request
        assert guard.check("", r"a+b\div c", user_input=request), request
        assert not guard.check("", r"\frac{a+b}{c}", user_input=request), request


def test_negated_chinese_fraction_requests_do_not_force_a_fraction():
    guard = OperatorDriftGuard()
    requests = [
        "不要写成分式。",
        "不用分式。",
        "不要 写为 分数。",
        "不要表示为分式。",
        "不要使用分数。",
        "请勿写成分式。",
        "无需写为分数。",
        "不必使用分式。",
        "不要把结果写成分式。",
        "不用分式，保留除号。",
        "检查这两个分数。",
    ]
    for request in requests:
        assert r"\frac" not in guard.forced_operators("", request), request
        assert not guard.check("", r"(a+b)\div c", user_input=request), request


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


def test_explicit_chinese_paired_set_operations_require_both_operators():
    guard = OperatorDriftGuard()
    for request in (
        "集合 A 与集合 B 的并集和交集",
        "写出 A、B 的交集与并集。",
        "不要计算，请描述 A 和 B 的并集及交集。",
    ):
        assert set(guard.forced_operators("", request)) == {r"\cup", r"\cap"}
        assert guard.missing_requirements("", r"A \cup B", user_input=request) == [r"\cap"]
        assert guard.missing_requirements("", r"A \cap B", user_input=request) == [r"\cup"]
        assert not guard.check("", r"A \cup B,\quad A \cap B", user_input=request)
        assert guard.check("", r"A \cup B\caption{x}", user_input=request)


def test_paired_set_anchor_does_not_expand_single_negated_or_filename_requests():
    guard = OperatorDriftGuard()
    for request in (
        "集合 A 与集合 B 的并集",
        "集合 A 与集合 B 的交集",
        "不要写并集和交集。",
        "只写并集，不要写交集。",
        "并集和交集.png",
    ):
        assert not guard.forced_operators("", request), request


def test_sequence_upper_and_lower_limits_preserve_distinct_notation():
    guard = OperatorDriftGuard()
    for label, command, alternate, decorated in (
        ("上", r"\limsup", r"\varlimsup", r"\overline{\lim}"),
        ("下", r"\liminf", r"\varliminf", r"\underline{\lim}"),
    ):
        request = f"数列 a 下标 n 的{label}极限"
        assert guard.forced_operators("", request) == [command]
        assert guard.check("", r"\lim_{n\to\infty}a_n", user_input=request)
        for notation in (command, alternate, decorated):
            assert not guard.check("", notation + r"_{n\to\infty}a_n", user_input=request)
        assert guard.check("", command + "extra", user_input=request)
        assert not guard.forced_operators("", "不要写" + request)
        assert not guard.forced_operators("", request.replace("的", "不要求的"))
        opposite = r"\liminf" if label == "上" else r"\limsup"
        assert guard.check("", opposite + r"_{n\to\infty}a_n", user_input=request)
    for request in ("数列 a 下标 n 的极限", "上极限.png", "积分的上极限"):
        assert not guard.forced_operators("", request)


def test_line_integral_does_not_assume_an_unspecified_closed_curve():
    guard = OperatorDriftGuard()
    request = "沿曲线 C 的线积分 f ds"
    assert guard.check("", r"\oint_C f\,ds", user_input=request)
    assert guard.check("", r"\int_C f\,ds + \oint_C f\,ds", user_input=request)
    assert not guard.check("", r"\int_C f\,ds", user_input=request)
    assert not guard.check("", r"\int\limits_C f\,ds", user_input=request)
    for other in (
        "沿闭合曲线 C 的线积分 f ds",
        "沿曲线 C 的闭合线积分 f ds",
        "不要写沿曲线 C 的线积分 f ds",
        "沿曲线 C 的线积分 f ds.png",
    ):
        assert not guard.forced_operators("", other)


def test_line_integral_pretranslation_does_not_add_closure():
    from texada.core.symbols import SymbolEngine

    engine = SymbolEngine()
    assert r"\int" in engine.pre_translate("沿曲线 C 的线积分 f ds")
    assert r"\oint" not in engine.pre_translate("沿曲线 C 的线积分 f ds")
    assert r"\oint" in engine.pre_translate("闭合线积分")


def test_explicit_nth_ordinary_derivative_preserves_denominator_order():
    guard = OperatorDriftGuard()
    request = "f 对 x 的 n 阶导数"
    for candidate in (
        r"\frac{d^n f}{dx}",
        r"\frac{d^n f}{dx^2}",
        r"\frac{d^n f}{dy^n}",
        r"\frac{d^n g}{dx^n}",
        r"\frac{\partial^n f}{\partial x^n}",
        r"\frac{d^n f}{dx} + x^n",
        r"\text{\frac{d^n f}{dx^n}}",
        r"f^{(n)}(y)",
    ):
        assert guard.check("", candidate, user_input=request), candidate
    for candidate in (
        r"\frac{d^n f}{dx^n}",
        r"\frac{d^{n}f}{d x^{n}}",
        r"\dfrac{\mathrm{d}^{n} f}{\mathrm{d} x^{n}}",
        r"f^{(n)}(x)",
        r"\tfrac{d^n f(x)}{dx^n}",
    ):
        # Pretranslation normally introduces a fraction; alternative notation
        # must not be rejected solely for omitting that implicit fraction.
        assert not guard.check(r"\frac{d}{dx}", candidate, user_input=request), candidate
    for request in ("不要写 f 对 x 的 n 阶导数", "f 对 x 的 n 阶偏导数", "f 对 x 的一阶导数"):
        assert not guard.forced_operators("", request)


def test_nth_derivative_template_binds_other_function_and_variable_names():
    guard = OperatorDriftGuard()
    request = "g 对 t 的 n 阶导数。"
    assert not guard.check("", r"\frac{d^n g}{dt^n}", user_input=request)
    assert not guard.check("", r"g^{(n)}(t)", user_input=request)
    assert guard.check("", r"\frac{d^n g}{dx^n}", user_input=request)
    assert guard.check("", r"f^{(n)}(t)", user_input=request)


def test_explicit_second_ordinary_derivative_preserves_order_and_kind():
    guard = OperatorDriftGuard()
    description = "y 对 x 的二阶导数"
    for candidate in (
        r"\frac{\partial y}{\partial x}",
        r"\frac{\partial^2 y}{\partial x^2}",
        r"\frac{dy}{dx}",
        r"\frac{d^2y}{dx}",
        r"\frac{d^2y}{dt^2}",
        r"\frac{d^2f}{dx^2}",
        r"\frac{dy}{dx}+x^2+y^2",
        r"y'(x)",
        r"\text{y''}",
    ):
        assert guard.check("", candidate, user_input=description), candidate
    for candidate in (
        r"\frac{d^2y}{dx^2}",
        r"\dfrac{\mathrm{d}^{2}y}{\mathrm{d}x^{2}}",
        r"\tfrac{d^2y(x)}{dx^2}",
        "y''", "y''(x)", r"y^{\prime\prime}",
        r"y^{\prime\prime}(x)", r"y^{(2)}(x)",
    ):
        assert not guard.check(r"\frac{d}{dx}", candidate, user_input=description), candidate
    for description in (
        "不要写 y 对 x 的二阶导数", "y 对 x 的二阶偏导数",
        "y 对 x 的一阶导数", "y 对 x 的二阶导数.png",
    ):
        assert not guard.forced_operators("", description)


def test_second_derivative_template_binds_other_names():
    guard = OperatorDriftGuard()
    description = "g 对 t 的二阶导数。"
    assert not guard.check("", r"\frac{d^2g}{dt^2}", user_input=description)
    assert not guard.check("", "g''(t)", user_input=description)
    assert guard.check("", "g''(x)", user_input=description)
    assert guard.check("", "f''(t)", user_input=description)
