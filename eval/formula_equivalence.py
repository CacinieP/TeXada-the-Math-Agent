"""Conservative assistance for full-formula review, never an automatic math judge.

Whole-tree approved notation matching is separate from bounded symbolic evidence.
An algebraic match does not establish domain preservation, task completion or intent.
The final benchmark stores a separate, explicit mathematical verdict for every row.
"""
from __future__ import annotations

import multiprocessing as mp
from typing import Any

from texada.semantic.structure import canonical_structure

_RATIONAL_CASES = frozenset({"001", "002", "003", "004", "005", "006", "011", "013",
                             "014", "015", "022", "024", "025", "034"})
_VECTOR_LETTERS = {
    "008": {"x"}, "057": {"F"}, "058": {"F"}, "067": {"F", "r"},
    "080": {"F", "r", "n"}, "081": {"x"}, "086": {"a", "b"},
    "087": {"a", "b"}, "088": {"v"},
}


def _notation(nodes: list[dict], case_id: str) -> list[dict]:
    result = []
    for node in nodes:
        children = node.get("children", [])
        if node.get("kind") in {"font", "accent"} and children:
            content = children[0].get("children", [])
            letters = {c.get("value") for c in content if c.get("kind") == "symbol"}
            simple = bool(content) and all(c.get("kind") == "symbol" for c in content)
            font = node.get("value")
            if (simple and letters <= _VECTOR_LETTERS.get(case_id, set())
                    and font in {"mathbf", "boldsymbol", "\\vec"}):
                result.extend(_notation(content, case_id))
                continue
            # Math Roman is only approved for the same already named Latin
            # scalar symbols. Blackboard/script fonts and constants e/i remain.
            if (simple and font == "mathrm" and all(
                isinstance(c.get("value"), str) and len(c["value"]) == 1
                and c["value"].isascii() and c["value"].isalpha()
                and c["value"] not in {"e", "i"} for c in content
            )):
                result.extend(_notation(content, case_id))
                continue
            if (case_id in {"085", "086", "089"} and simple
                    and font == "mathsf" and letters == {"T"}):
                result.extend(_notation(content, case_id))
                continue
        normalized = {key: value for key, value in node.items() if key != "children"}
        if children:
            normalized["children"] = _notation(children, case_id)
        if (case_id in {"065", "066", "068"} and node.get("kind") == "operator"
                and node.get("value") in {r"\int", r"\iint", r"\iiint"}):
            normalized["value"] = "integral_over_declared_measure"
        if (case_id in {"085", "086", "089"} and node.get("kind") == "symbol"
                and node.get("value") == r"\top"):
            normalized["value"] = "T"
        if (node.get("kind") == "delimited" and len(children) == 1
                and children[0].get("kind") == "array"
                and (node.get("left"), node.get("right")) in {("(", ")"), ("[", "]")}):
            normalized.update(left="matrix", right="matrix")
        result.append(normalized)
    return result


def notation_match(candidate: str, reference: str, case_id: str) -> bool:
    left, _ = canonical_structure(candidate)
    right, _ = canonical_structure(reference)
    return bool(right) and _notation(left, case_id) == _notation(right, case_id)


def _symbolic_worker(candidate: str, reference: str, output) -> None:
    try:
        import sympy as sp
        from sympy.parsing.latex import parse_latex

        left, right = (parse_latex(text, strict=True) for text in (candidate, reference))
        for expr in (left, right):
            if sp.count_ops(expr) > 150:
                raise ValueError("expression_size_limit")
            if expr.has(sp.Integral, sp.Sum, sp.Product, sp.Limit, sp.Derivative, sp.Float):
                raise ValueError("unsupported_symbolic_operation")
        equation = isinstance(left, sp.Equality) and isinstance(right, sp.Equality)
        if isinstance(left, sp.Equality) != isinstance(right, sp.Equality):
            raise ValueError("expression_equation_mismatch")
        if equation:
            left, right = left.lhs-left.rhs, right.lhs-right.rhs
            if left.free_symbols != right.free_symbols:
                raise ValueError("equation_variable_mismatch")
            ratio = sp.cancel(left/right)
            matched = ratio.is_number is True and ratio.is_zero is False
        else:
            matched = sp.cancel(left-right) == 0
        output.put({"status": "SAME_ON_COMMON_DOMAIN" if matched else "NOT_PROVED",
                    "method": "strict-ANTLR-plus-exact-SymPy", "domain_verified": False,
                    "reference_expr": sp.srepr(right), "candidate_expr": sp.srepr(left)})
    except Exception as exc:
        output.put({"status": "UNSUPPORTED", "reason": type(exc).__name__})


def symbolic_evidence(candidate: str, reference: str, *, timeout=3.0) -> dict[str, Any]:
    if len(candidate) > 2048 or len(reference) > 2048:
        return {"status": "UNSUPPORTED", "reason": "expression_size_limit"}
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_symbolic_worker, args=(candidate, reference, queue))
    process.start()
    try:
        result = queue.get(timeout=timeout)
    except Exception:
        result = {"status": "NOT_CHECKED", "reason": "worker_timeout_or_failure"}
    finally:
        process.join(timeout=.1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=.5)
        queue.close()
        queue.join_thread()
    return result


def assist(candidate: str | None, entry: dict, *, original=False) -> dict:
    if not isinstance(candidate, str) or not candidate.strip():
        return {"status": "NO_CANDIDATE", "final_verdict": False}
    variants = [r["latex"] for r in entry["references"]]
    if original:
        variants.extend(entry.get("original_interpretation_alternatives", []))
    for index, reference in enumerate(variants):
        try:
            if notation_match(candidate, reference, entry["case_id"]):
                return {"status": "WHOLE_NOTATION_MATCH", "reference_index": index,
                        "final_verdict": False}
        except Exception:
            continue
    if entry["case_id"] in _RATIONAL_CASES:
        evidence = symbolic_evidence(candidate, variants[0])
        return {"status": "SYMBOLIC_ASSISTANCE", "evidence": evidence,
                "final_verdict": False}
    return {"status": "REQUIRES_MATHEMATICAL_REVIEW", "final_verdict": False}
