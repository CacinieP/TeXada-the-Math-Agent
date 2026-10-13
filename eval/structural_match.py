"""Conservative whole-expression structure checks, separate from containment.

Only explicit, full-expression references are eligible. The canonicalizer reads
the raw, pinned KaTeX AST: the product's tolerant SemanticUnit mapper deliberately
drops some presentation fields and is not a strict evaluation oracle.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from texada.semantic.katex import MAX_NESTING_DEPTH as MAX_NESTING_DEPTH
from texada.semantic.katex import shared_katex_parser
from texada.semantic.structure import (
    NORMALIZATION_VERSION,
    canonical_structure,
)
from texada.semantic.structure import (
    UnsupportedStructure as _Unsupported,
)

Status = Literal["MATCH", "DIFFERENT", "UNSUPPORTED", "NOT_CHECKED"]
@dataclass
class StructuralResult:
    status: Status
    reason: str
    normalization_version: str = NORMALIZATION_VERSION
    parser_backend: str | None = None
    candidate_tree_sha256: str | None = None
    reference_tree_sha256: str | None = None
    reference_id: str | None = None
    reference_source: str | None = None
    reference_review_status: str | None = None
    unsupported_nodes: list[str] = field(default_factory=list)
    first_difference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(latex: str) -> tuple[list[dict], str]:
    return canonical_structure(latex, parser=shared_katex_parser())


def _hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _difference(before: Any, after: Any, path: str = "root") -> str | None:
    if type(before) is not type(after):
        return path
    if isinstance(before, dict):
        if before.keys() != after.keys():
            return path
        for key in before:
            found = _difference(before[key], after[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(before, list):
        if len(before) != len(after):
            return f"{path}.length"
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            role = left.get("role") if isinstance(left, dict) and isinstance(right, dict) else None
            child_path = (f"{path}.{role}" if role and role == right.get("role")
                          else f"{path}[{index}]")
            found = _difference(left, right, child_path)
            if found:
                return found
    elif before != after:
        return path
    return None


def compare_structure(candidate_latex: str, reference_latex: str) -> StructuralResult:
    """Compare two complete expressions, never the original natural language."""
    if not isinstance(reference_latex, str) or not reference_latex.strip():
        return StructuralResult("NOT_CHECKED", "missing_full_reference")
    if not isinstance(candidate_latex, str):
        return StructuralResult("NOT_CHECKED", "candidate_unavailable")
    trees = []
    backend = None
    for side, latex in (("reference", reference_latex), ("candidate", candidate_latex)):
        try:
            tree, backend = _canonical(latex)
            if side == "reference" and not tree:
                raise _Unsupported("empty_reference_expression")
            trees.append(tree)
        except _Unsupported as exc:
            return StructuralResult("UNSUPPORTED", f"{side}:{exc}", parser_backend=backend,
                                    unsupported_nodes=[f"{side}:{exc}"])
        except Exception:
            return StructuralResult("UNSUPPORTED", f"{side}:parser_unavailable")
    reference, candidate = trees
    try:
        difference = _difference(reference, candidate)
        candidate_hash = _hash(candidate)
        reference_hash = _hash(reference)
    except (MemoryError, RecursionError):
        return StructuralResult("UNSUPPORTED", "comparison_resource_limit",
                                parser_backend=backend,
                                unsupported_nodes=["comparison_resource_limit"])
    return StructuralResult(
        "DIFFERENT" if difference else "MATCH",
        "whole_expression_differs" if difference else "whole_expression_matches",
        parser_backend=backend, candidate_tree_sha256=candidate_hash,
        reference_tree_sha256=reference_hash, first_difference=difference,
    )


def load_references(path: Path | None, *, text: str | None = None) -> dict[str, list[dict]]:
    """Load opt-in authored references; anchors and input text are not a source."""
    if path is None:
        return {}
    data = yaml.safe_load(text if text is not None else path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("structure references require schema_version 1")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("structure references require an entries list")
    references = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scope") != "full_expression":
            raise ValueError("structure references must declare full_expression scope")
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in references:
            raise ValueError("structure reference case ids must be unique nonempty strings")
        variants = entry.get("references")
        if not isinstance(variants, list) or not variants:
            raise ValueError("each structure reference needs explicit variants")
        for variant in variants:
            if (not isinstance(variant, dict) or not isinstance(variant.get("latex"), str)
                    or not variant["latex"].strip()
                    or any(not isinstance(variant.get(key), str) or not variant[key].strip()
                           for key in ("reference_id", "reference_source", "review_status"))):
                raise ValueError("reference variants need latex, id, source and review status")
        references[case_id] = variants
    return references


def check_references(candidate: str | None, references: list[dict]) -> StructuralResult:
    if not references:
        return StructuralResult("NOT_CHECKED", "missing_full_reference")
    results = []
    for reference in references:
        result = compare_structure(candidate, reference["latex"])
        result.reference_id = reference["reference_id"]
        result.reference_source = reference["reference_source"]
        result.reference_review_status = reference["review_status"]
        results.append(result)
        if result.status == "MATCH":
            return result
    # A failed unsupported alternative cannot prove rejection of the entire
    # approved OR-set. Keep it visible rather than calling the set DIFFERENT.
    for status in ("NOT_CHECKED", "UNSUPPORTED", "DIFFERENT"):
        if result := next((r for r in results if r.status == status), None):
            return result
    raise AssertionError("unexpected structural result")


def summarize_structure(rows: list[dict]) -> dict:
    counts = {status: 0 for status in ("MATCH", "DIFFERENT", "UNSUPPORTED", "NOT_CHECKED")}
    for row in rows:
        counts[row["strict_structure"]["status"]] += 1
    comparable = counts["MATCH"] + counts["DIFFERENT"]
    attempted = comparable + counts["UNSUPPORTED"]
    return {"counts": counts, "comparable": comparable, "attempted": attempted,
            "total": len(rows),
            "match_rate_comparable": counts["MATCH"] / comparable if comparable else None,
            "comparable_coverage": comparable / len(rows) if rows else None}
