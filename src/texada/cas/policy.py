"""Conservative comparison policy executed inside the CAS worker."""

from __future__ import annotations

from typing import Any

from texada.cas.model import CASBasis, CASEvidenceGrade, CASResult, CASStatus

_WITNESS_VALUES = (0, 1, -1, 2, -2)
POLICY_VERSION = "cas-policy-v1"


def compare_expressions(
    lhs: Any,
    rhs: Any,
    *,
    assumptions: list[str] | None = None,
) -> CASResult:
    """Compare controlled SymPy objects without trusting ``equals(False)``."""
    import sympy as sp

    assumptions = assumptions or []
    convergence = _convergence_observations(lhs, rhs)
    if isinstance(lhs, sp.Equality) or isinstance(rhs, sp.Equality):
        if not isinstance(lhs, sp.Equality) or not isinstance(rhs, sp.Equality):
            return _unknown(
                assumptions,
                "relation_mismatch",
                "an equation and a scalar expression are not compared in v1",
            )
        return _compare_equations(lhs, rhs, assumptions)

    lhs_evaluated, unsafe = _safe_doit(lhs)
    if unsafe:
        return _unsafe_result(
            assumptions,
            "lhs",
            unsafe,
            observation=convergence,
        )
    rhs_evaluated, unsafe = _safe_doit(rhs)
    if unsafe:
        return _unsafe_result(
            assumptions,
            "rhs",
            unsafe,
            observation=convergence,
        )

    exact_difference = _exact_difference(lhs_evaluated, rhs_evaluated)
    if exact_difference is not None and (
        exact_difference == 0 or exact_difference.is_zero is True
    ):
        return CASResult(
            status=CASStatus.EQUIVALENT,
            basis=CASBasis.EXACT_NORMALIZATION,
            evidence_grade=CASEvidenceGrade.EXACT,
            assumptions=assumptions,
            observation={
                **convergence,
                "difference_srepr": sp.srepr(exact_difference),
            },
        )

    counterexample = _find_counterexample(lhs_evaluated, rhs_evaluated)
    if counterexample is not None:
        witness, lhs_value, rhs_value = counterexample
        return CASResult(
            status=CASStatus.DIFFERENT,
            basis=CASBasis.EXACT_COUNTEREXAMPLE,
            evidence_grade=CASEvidenceGrade.EXACT,
            assumptions=assumptions,
            witness=witness,
            lhs_value=_json_exact(lhs_value),
            rhs_value=_json_exact(rhs_value),
            observation=convergence,
        )

    equals_observation = lhs_evaluated.equals(rhs_evaluated)
    if equals_observation is True:
        return CASResult(
            status=CASStatus.EQUIVALENT,
            basis=CASBasis.SYMPY_EQUALS_TRUE,
            evidence_grade=CASEvidenceGrade.SYMBOLIC_HEURISTIC,
            assumptions=assumptions,
            observation={**convergence, "equals": True},
        )
    if equals_observation is False:
        return CASResult(
            status=CASStatus.UNKNOWN,
            basis=CASBasis.SYMPY_EQUALS_FALSE_OBSERVATION,
            evidence_grade=CASEvidenceGrade.OBSERVATION,
            assumptions=assumptions,
            observation={**convergence, "equals": False},
            reason=(
                "SymPy returned False, but False alone is not proof of mathematical "
                "difference for unevaluated or assumption-sensitive objects"
            ),
            reason_code="equals_false_is_observation",
        )
    return _unknown(
        assumptions,
        "equals_inconclusive",
        "SymPy could not establish equivalence and no exact counterexample was found",
        observation={**convergence, "equals": None},
    )


def _compare_equations(lhs: Any, rhs: Any, assumptions: list[str]) -> CASResult:
    import sympy as sp

    lhs_residual, unsafe = _safe_doit(lhs.lhs - lhs.rhs)
    if unsafe:
        return _unsafe_result(assumptions, "lhs_equation", unsafe)
    rhs_residual, unsafe = _safe_doit(rhs.lhs - rhs.rhs)
    if unsafe:
        return _unsafe_result(assumptions, "rhs_equation", unsafe)

    difference = _exact_difference(lhs_residual, rhs_residual)
    if difference is not None and (difference == 0 or difference.is_zero is True):
        return CASResult(
            status=CASStatus.EQUIVALENT,
            basis=CASBasis.EXACT_NORMALIZATION,
            evidence_grade=CASEvidenceGrade.EXACT,
            assumptions=assumptions,
            observation={"residual_difference_srepr": sp.srepr(difference)},
        )

    if rhs_residual != 0:
        factor = _exact_ratio(lhs_residual, rhs_residual)
        if factor is not None:
            return CASResult(
                status=CASStatus.EQUIVALENT,
                basis=CASBasis.EQUATION_CONSTANT_FACTOR,
                evidence_grade=CASEvidenceGrade.EXACT,
                assumptions=assumptions,
                observation={"factor": _json_exact(factor)},
            )

    counterexample = _find_equation_counterexample(lhs, rhs)
    if counterexample is not None:
        witness, lhs_value, rhs_value = counterexample
        return CASResult(
            status=CASStatus.DIFFERENT,
            basis=CASBasis.EXACT_COUNTEREXAMPLE,
            evidence_grade=CASEvidenceGrade.EXACT,
            assumptions=assumptions,
            witness=witness,
            lhs_value=lhs_value,
            rhs_value=rhs_value,
        )
    return _unknown(
        assumptions,
        "equation_inconclusive",
        "equation residuals were not provably equivalent and no exact witness was found",
    )


def _safe_doit(expression: Any) -> tuple[Any, str]:
    import sympy as sp

    evaluated = expression.doit()
    if evaluated.has(sp.Piecewise):
        return evaluated, "piecewise_result"
    if evaluated.has(sp.oo, -sp.oo, sp.zoo, sp.nan):
        return evaluated, "non_finite_result"
    if evaluated.has(sp.Integral, sp.Sum, sp.Product):
        return evaluated, "unevaluated_operator"
    return evaluated, ""


def _exact_difference(lhs: Any, rhs: Any) -> Any | None:
    """Return a rational/algebraic normalization, never a heuristic simplify."""
    import sympy as sp

    difference = lhs - rhs
    if difference.has(sp.Function):
        return None
    return sp.cancel(sp.together(difference))


def _exact_ratio(lhs: Any, rhs: Any) -> Any | None:
    import sympy as sp

    if lhs.has(sp.Function) or rhs.has(sp.Function):
        return None
    factor = sp.cancel(sp.together(lhs / rhs))
    if (
        not factor.free_symbols
        and factor.is_zero is False
        and _is_finite_exact(factor)
    ):
        return factor
    return None


def _convergence_observations(lhs: Any, rhs: Any) -> dict[str, Any]:
    """Record convergence as evidence; never turn divergence into equality to oo."""
    import sympy as sp

    observations: dict[str, Any] = {}
    for side, expression in (("lhs", lhs), ("rhs", rhs)):
        if not isinstance(expression, sp.Sum):
            continue
        try:
            convergent = expression.is_convergent()
        except NotImplementedError:
            observations[f"{side}_convergence"] = "unknown"
        except Exception as exc:
            observations[f"{side}_convergence"] = {
                "status": "error",
                "type": type(exc).__name__,
            }
        else:
            observations[f"{side}_convergence"] = (
                "convergent" if convergent == sp.S.true else "divergent"
            )
    return observations


def _find_counterexample(lhs: Any, rhs: Any) -> tuple[dict[str, Any], Any, Any] | None:
    import sympy as sp

    symbols = sorted(lhs.free_symbols | rhs.free_symbols, key=lambda item: item.name)
    if not symbols:
        if _is_finite_exact(lhs) and _is_finite_exact(rhs):
            difference = sp.simplify(lhs - rhs)
            if difference.is_zero is False:
                return {}, lhs, rhs
        return None

    for symbol in symbols:
        for raw_value in _WITNESS_VALUES:
            value = sp.Integer(raw_value)
            if not _candidate_allowed(symbol, value):
                continue
            substitutions = {
                item: value if item == symbol else sp.Integer(1)
                for item in symbols
            }
            if any(
                not _candidate_allowed(item, candidate)
                for item, candidate in substitutions.items()
            ):
                continue
            lhs_value = sp.simplify(lhs.subs(substitutions).doit())
            rhs_value = sp.simplify(rhs.subs(substitutions).doit())
            if not (_is_finite_exact(lhs_value) and _is_finite_exact(rhs_value)):
                continue
            difference = sp.simplify(lhs_value - rhs_value)
            if difference.is_zero is False:
                witness = {
                    item.name: _json_exact(candidate)
                    for item, candidate in substitutions.items()
                }
                return witness, lhs_value, rhs_value
    return None


def _find_equation_counterexample(
    lhs: Any,
    rhs: Any,
) -> tuple[dict[str, Any], bool, bool] | None:
    import sympy as sp

    symbols = sorted(lhs.free_symbols | rhs.free_symbols, key=lambda item: item.name)
    for symbol in symbols:
        for raw_value in _WITNESS_VALUES:
            value = sp.Integer(raw_value)
            if not _candidate_allowed(symbol, value):
                continue
            substitutions = {
                item: value if item == symbol else sp.Integer(1)
                for item in symbols
            }
            if any(
                not _candidate_allowed(item, candidate)
                for item, candidate in substitutions.items()
            ):
                continue
            lhs_values = (
                sp.simplify(lhs.lhs.subs(substitutions).doit()),
                sp.simplify(lhs.rhs.subs(substitutions).doit()),
            )
            rhs_values = (
                sp.simplify(rhs.lhs.subs(substitutions).doit()),
                sp.simplify(rhs.rhs.subs(substitutions).doit()),
            )
            if not all(_is_finite_exact(item) for item in (*lhs_values, *rhs_values)):
                continue
            lhs_truth = sp.simplify(lhs_values[0] - lhs_values[1]).is_zero
            rhs_truth = sp.simplify(rhs_values[0] - rhs_values[1]).is_zero
            if lhs_truth is not None and rhs_truth is not None and lhs_truth != rhs_truth:
                witness = {
                    item.name: _json_exact(candidate)
                    for item, candidate in substitutions.items()
                }
                return witness, bool(lhs_truth), bool(rhs_truth)
    return None


def _candidate_allowed(symbol: Any, value: Any) -> bool:
    checks = {
        "positive": value.is_positive,
        "negative": value.is_negative,
        "nonnegative": value.is_nonnegative,
        "nonpositive": value.is_nonpositive,
        "nonzero": value.is_nonzero,
        "integer": value.is_integer,
        "real": value.is_real,
    }
    for key, actual in checks.items():
        expected = symbol.assumptions0.get(key)
        if expected is True and actual is not True:
            return False
        if expected is False and actual is True:
            return False
    return True


def _is_finite_exact(value: Any) -> bool:
    import sympy as sp

    return (
        not value.free_symbols
        and value.is_number is True
        and value.is_finite is True
        and not value.has(sp.Float, sp.Piecewise, sp.oo, -sp.oo, sp.zoo, sp.nan)
    )


def _json_exact(value: Any) -> Any:
    import sympy as sp

    if isinstance(value, sp.Integer):
        return int(value)
    return str(value)


def _unsafe_result(
    assumptions: list[str],
    side: str,
    reason_code: str,
    *,
    observation: dict[str, Any] | None = None,
) -> CASResult:
    return CASResult(
        status=CASStatus.UNKNOWN,
        basis=CASBasis.UNSAFE_EVALUATION_RESULT,
        evidence_grade=CASEvidenceGrade.OBSERVATION,
        assumptions=assumptions,
        observation=observation or {},
        reason=f"{side} evaluation produced {reason_code.replace('_', ' ')}",
        reason_code=reason_code,
    )


def _unknown(
    assumptions: list[str],
    reason_code: str,
    reason: str,
    *,
    observation: dict[str, Any] | None = None,
) -> CASResult:
    return CASResult(
        status=CASStatus.UNKNOWN,
        basis=CASBasis.INCONCLUSIVE,
        evidence_grade=CASEvidenceGrade.OBSERVATION,
        assumptions=assumptions,
        observation=observation or {},
        reason=reason,
        reason_code=reason_code,
    )
