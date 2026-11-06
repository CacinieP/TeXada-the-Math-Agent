"""Finite source constraints for indexed sums and sums of region integrals.

The recognizer accepts whole descriptions containing single-letter symbols and
indices. Region names are limited to omega/Omega aliases. Unspecified summation
bounds and integration measures stay implicit in the generated notation.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from texada.core.inference_fingerprint import canonical_sha256
from texada.core.scope import requests_computation, transcription_description
from texada.semantic.structure import (
    NORMALIZATION_VERSION,
    UnsupportedStructure,
    canonical_structure,
)

_INDEXED_SYMBOL = r"(?:[A-Za-z]{2}|[A-Za-z]_[A-Za-z]|[A-Za-z]_\{[A-Za-z]\})"
_SUM_REQUEST = r"写(?:出)?(?:一个|个)?求和公式\s*[,，]\s*"
_SUM_PREFIX = rf"(?:{_SUM_REQUEST})?"
_AMBIGUOUS_JOINED_SYMBOLS = frozenset({"ln", "pi", "Pi", "mu", "nu", "xi", "Xi"})
_INDEXED_SUM = re.compile(rf"{_SUM_PREFIX}对\s*(?P<term>{_INDEXED_SYMBOL})\s*求和")
_DOMAIN_SUM = re.compile(
    r"对\s*(?P<function>[A-Za-z])\s*\(\s*(?P<argument>[A-Za-z])\s*\)\s*"
    r"进行求和\s*[,，]\s*其中\s*(?P<index>[A-Za-z])\s*取遍\s*"
    r"(?P<domain>整数(?:集)?|(?:集合\s*)?[A-Za-z])\s*中的元素"
)
_REGION_SUM = re.compile(
    rf"{_SUM_REQUEST}其中每一项是函数\s*(?P<function>{_INDEXED_SYMBOL})\s*"
    r"在\s*(?P<region>\\?(?:omega|Omega)|ω|Ω)"
    r"(?P<index>[A-Za-z]|_[A-Za-z]|_\{[A-Za-z]\}|_)?\s*上的积分"
)


@dataclass(frozen=True)
class TranscriptionSpec:
    """A locally recognized source and its bounded display contract."""

    kind: str
    latex: str
    rule: str
    unspecified_fields: tuple[str, ...] = ()
    clarification: str = ""


def _indexed_parts(symbol: str) -> tuple[str, str]:
    return symbol[0], symbol.translate(str.maketrans("", "", "_{}"))[1]


def recognize_transcription(text: str) -> TranscriptionSpec | None:
    """Recognize complete supported descriptions without filling missing roles."""
    if requests_computation(text):
        return None
    description = transcription_description(text.strip().rstrip(",，。.;；!！?？"))
    indexed = _INDEXED_SUM.fullmatch(description)
    if indexed:
        if indexed["term"] in _AMBIGUOUS_JOINED_SYMBOLS:
            return TranscriptionSpec(
                kind="indexed_sum", latex="", rule="nl_indexed_sum",
                clarification="连写符号可能表示命名算符或字母，请用下划线明确下标。",
            )
        base, index = _indexed_parts(indexed["term"])
        return TranscriptionSpec(
            kind="indexed_sum",
            latex=rf"\sum_{{{index}}} {base}_{index}",
            rule="nl_indexed_sum",
            unspecified_fields=("sum_bounds",),
        )
    domain = _DOMAIN_SUM.fullmatch(description)
    if domain:
        if domain["argument"] != domain["index"]:
            return TranscriptionSpec(
                kind="domain_sum", latex="", rule="nl_domain_sum",
                clarification="函数自变量与求和变量不一致，请明确求和变量。",
            )
        set_name = domain["domain"]
        set_latex = r"\mathbb{Z}" if set_name.startswith("整数") else set_name[-1]
        return TranscriptionSpec(
            kind="domain_sum",
            latex=(rf"\sum_{{{domain['index']} \in {set_latex}}} "
                   rf"{domain['function']}({domain['argument']})"),
            rule="nl_domain_sum",
        )
    region = _REGION_SUM.fullmatch(description)
    if not region:
        return None
    if region["function"] in _AMBIGUOUS_JOINED_SYMBOLS:
        return TranscriptionSpec(
            kind="region_integral_sum", latex="", rule="nl_region_integral_sum",
            clarification="连写函数名可能表示命名算符或字母，请用下划线明确下标。",
        )
    base, index = _indexed_parts(region["function"])
    region_index = (region["index"] or "").translate(str.maketrans("", "", "_{}"))
    if not region_index:
        clarification = "积分区域缺少下标，请明确区域下标。"
    elif region_index != index:
        clarification = "函数下标与积分区域下标不一致，请明确求和项与区域的对应关系。"
    else:
        clarification = ""
    region_name = region["region"].lstrip("\\").replace("ω", "omega").replace("Ω", "Omega")
    return TranscriptionSpec(
        kind="region_integral_sum",
        latex=rf"\sum_{{{index}}} \int_{{\{region_name}_{index}}} {base}_{index}"
        if not clarification else "",
        rule="nl_region_integral_sum",
        unspecified_fields=("sum_bounds", "integration_measure"),
        clarification=clarification,
    )


def check_transcription(spec: TranscriptionSpec, latex: str) -> dict[str, Any]:
    """Compare the actual candidate with the recognized source display structure."""
    result: dict[str, Any] = {
        "verdict": "NOT_CHECKED",
        "spec": asdict(spec),
        "coverage": {
            "scope": "finite_transcription_display",
            "checks": ["term_symbols", "indices", "operator_roles", "specified_domains"],
            "unspecified_fields": list(spec.unspecified_fields),
        },
        "normalization_version": f"transcription-display-v1/{NORMALIZATION_VERSION}",
        "diagnostics": [],
    }
    if spec.clarification:
        result["diagnostics"] = [spec.clarification]
        return result
    if not isinstance(latex, str) or not latex.strip():
        result["diagnostics"] = ["transcription candidate is unavailable"]
        return result
    try:
        expected, backend = canonical_structure(spec.latex)
        candidate, backend = canonical_structure(latex)
    except UnsupportedStructure as exc:
        result.update(verdict="UNSUPPORTED", diagnostics=[str(exc)])
        return result
    except Exception:
        result.update(verdict="UNSUPPORTED", diagnostics=["transcription parser unavailable"])
        return result
    matches = expected == candidate
    result.update(
        verdict="MATCH" if matches else "DIFFERENT",
        parser_backend=backend,
        candidate_tree_sha256=canonical_sha256(candidate),
        expected_tree_sha256=canonical_sha256(expected),
        diagnostics=[] if matches else ["candidate differs from the source display contract"],
    )
    return result
