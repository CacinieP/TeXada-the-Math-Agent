"""Conservative whole-expression structure checks, separate from containment.

Only explicit, full-expression references are eligible. The canonicalizer reads
the raw, pinned KaTeX AST: the product's tolerant SemanticUnit mapper deliberately
drops some presentation fields and is not a strict evaluation oracle.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from texada.semantic.katex import MAX_NESTING_DEPTH, shared_katex_parser

Status = Literal["MATCH", "DIFFERENT", "UNSUPPORTED", "NOT_CHECKED"]
NORMALIZATION_VERSION = "katex-structure-v1"
MAX_EXPRESSION_CHARS = 32768
_OPERATOR_ROLES = {r"\int", r"\iint", r"\iiint", r"\oint", r"\sum", r"\prod", r"\lim"}
_DELIMITERS = {r"\lbrace": r"\{", r"\rbrace": r"\}", r"\lbrack": "[", r"\rbrack": "]"}
_SYMBOL_ALIASES = {r"\leq": r"\le", "≤": r"\le", r"\geq": r"\ge", "≥": r"\ge"}
_SOURCE_GUARD = re.compile(
    r"\\(?:placeholder|def|gdef|edef|xdef|let|futurelet|newcommand|renewcommand|providecommand)\b"
)
_FIELDS = {
    "ordgroup": {"body", "semisimple"},
    "styling": {"body", "style", "resetFont"},
    "sizing": {"body", "size"},
    "color": {"body", "color"},
    "kern": {"dimension"}, "spacing": {"text"},
    "mathord": {"text"}, "textord": {"text"}, "atom": {"text", "family"},
    "supsub": {"base", "sub", "sup"},
    "genfrac": {"numer", "denom", "continued", "hasBarLine", "leftDelim",
                "rightDelim", "barSize", "size"},
    "sqrt": {"body", "index"},
    "op": {"name", "body", "limits", "parentIsSupSub", "symbol",
           "alwaysHandleSupSub", "suppressBaseShift"},
    "leftright": {"body", "left", "right", "rightColor"},
    "array": {"body", "cols", "rowGaps", "hLinesBeforeRow", "arraystretch",
              "hskipBeforeAndAfter", "colSeparationType", "addJot"},
    "font": {"font", "body"},
    "accent": {"label", "base", "isStretchy", "isShifty"},
    "accentUnder": {"label", "base", "isStretchy", "isShifty"},
    "overline": {"body"}, "underline": {"body"},
}


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


class _Unsupported(ValueError):
    pass


def _check_node(node: dict) -> None:
    kind = node.get("type")
    if kind not in _FIELDS:
        raise _Unsupported(f"unsupported_katex_type:{kind or 'unknown'}")
    if node.get("mode", "math") != "math":
        raise _Unsupported(f"non_math_mode:{kind}")
    extra = node.keys() - (_FIELDS[kind] | {"type", "mode", "loc"})
    if extra:
        raise _Unsupported(f"unsupported_katex_fields:{kind}:{','.join(sorted(extra))}")


def _hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _delimiter(value: Any) -> str:
    if not isinstance(value, str):
        raise _Unsupported("missing_delimiter")
    return _DELIMITERS.get(value, value)


def _argument(node: Any, role: str, depth: int) -> dict:
    if node is None:
        raise _Unsupported(f"missing_{role}")
    children = _sequence(node, depth + 1)
    if not children:
        raise _Unsupported(f"empty_{role}")
    return {"role": role, "children": children}


def _scripts(node: dict, base: list[dict], depth: int) -> dict:
    if not base:
        raise _Unsupported("empty_script_base")
    operator = len(base) == 1 and base[0].get("value") in _OPERATOR_ROLES
    children = [{"role": "base", "children": base}]
    for key, role in (("sub", "lower_bound" if operator else "subscript"),
                      ("sup", "upper_bound" if operator else "superscript")):
        if node.get(key) is not None:
            children.append(_argument(node[key], role, depth))
    return {"kind": "script", "children": children}


def _sequence(nodes: Any, depth: int = 0) -> list[dict]:
    if depth > MAX_NESTING_DEPTH:
        raise _Unsupported("canonical_depth_limit")
    if isinstance(nodes, dict):
        nodes = [nodes]
    if not isinstance(nodes, list):
        raise _Unsupported("malformed_ast_children")
    result: list[dict] = []
    stack: list[tuple[str, list[dict]]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise _Unsupported("malformed_ast_node")
        _check_node(node)
        # KaTeX attaches a script after ordinary parentheses to the closing
        # token. Rebind it to that explicit group, preserving both delimiters.
        closing_script = node.get("type") == "supsub" and isinstance(node.get("base"), dict)
        token = node["base"] if closing_script else node
        _check_node(token)
        if token.get("type") == "atom" and token.get("family") in {"open", "close"}:
            delimiter = _delimiter(token.get("text"))
            if token["family"] == "open":
                if closing_script:
                    raise _Unsupported("script_on_open_delimiter")
                stack.append((delimiter, result))
                result = []
            else:
                if not stack:
                    raise _Unsupported("unmatched_close_delimiter")
                left, parent = stack.pop()
                group = {"kind": "delimited", "left": left, "right": delimiter,
                         "children": result}
                parent.append(_scripts(node, [group], depth) if closing_script else group)
                result = parent
            continue
        result.extend(_node(node, depth + 1))
    if stack:
        raise _Unsupported("unmatched_open_delimiter")
    return result


def _node(node: dict, depth: int) -> list[dict]:
    kind = node.get("type")
    if kind in {"ordgroup", "styling", "sizing", "color"}:
        return _sequence(node.get("body"), depth)
    if kind in {"kern", "spacing"}:
        return []
    if kind in {"mathord", "textord", "atom"}:
        value = node.get("text")
        if not isinstance(value, str) or not value:
            raise _Unsupported("empty_atom")
        if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value):
            raise _Unsupported("non_formula_text_atom")
        # Keep symbol order and type; no commutativity, arithmetic, or CAS.
        return [{"kind": "symbol", "value": _SYMBOL_ALIASES.get(value, value)}]
    if kind == "supsub":
        return [_scripts(node, _sequence(node.get("base"), depth), depth)]
    if kind == "genfrac":
        if node.get("continued") or node.get("barSize") is not None:
            raise _Unsupported("custom_fraction_presentation")
        if not isinstance(node.get("hasBarLine"), bool):
            raise _Unsupported("missing_fraction_bar_contract")
        return [{"kind": "fraction", "has_bar_line": node["hasBarLine"],
                 "left": _delimiter(node["leftDelim"]) if node.get("leftDelim") else None,
                 "right": _delimiter(node["rightDelim"]) if node.get("rightDelim") else None,
                 "children": [_argument(node.get("numer"), "numerator", depth),
                              _argument(node.get("denom"), "denominator", depth)]}]
    if kind == "sqrt":
        children = []
        if node.get("index") is not None:
            children.append(_argument(node["index"], "index", depth))
        children.append(_argument(node.get("body"), "radicand", depth))
        return [{"kind": "root", "children": children}]
    if kind == "op":
        name = node.get("name")
        if not isinstance(name, str) or not name or node.get("body"):
            raise _Unsupported("custom_operator")
        return [{"kind": "operator", "value": name}]
    if kind == "leftright":
        return [{"kind": "delimited", "left": _delimiter(node.get("left")),
                 "right": _delimiter(node.get("right")),
                 "children": _sequence(node.get("body"), depth)}]
    if kind == "array":
        if any(node.get("hLinesBeforeRow") or []):
            raise _Unsupported("array_partition_lines")
        columns = node.get("cols") or []
        if any(not isinstance(c, dict) or c.get("type") != "align" for c in columns):
            raise _Unsupported("array_column_partition")
        rows = node.get("body")
        if not isinstance(rows, list) or not rows or any(not isinstance(r, list) for r in rows):
            raise _Unsupported("malformed_array")
        width = len(rows[0])
        if not width or any(len(row) != width for row in rows):
            raise _Unsupported("ragged_array")
        return [{"kind": "array", "rows": len(rows), "columns": width,
                 "children": [{"role": f"row_{i}", "children": [
                     _argument(cell, f"column_{j}", depth) for j, cell in enumerate(row)]}
                     for i, row in enumerate(rows)]}]
    if kind == "font":
        return [{"kind": "font", "value": node.get("font"),
                 "children": [_argument(node.get("body"), "argument", depth)]}]
    if kind in {"accent", "accentUnder", "overline", "underline"}:
        return [{"kind": kind, "value": node.get("label") or kind,
                 "children": [_argument(node.get("base", node.get("body")),
                                        "argument", depth)]}]
    # In particular, text, phantom/smash/raisebox, rule and new node types
    # cannot silently disappear or pass by comparing equally lossy trees.
    raise _Unsupported(f"unsupported_katex_type:{kind or 'unknown'}")


def _canonical(latex: str) -> tuple[list[dict], str]:
    if len(latex) > MAX_EXPRESSION_CHARS:
        raise _Unsupported("expression_size_limit")
    if _SOURCE_GUARD.search(latex):
        raise _Unsupported("unresolved_hole_or_custom_macro_definition")
    result = shared_katex_parser().parse(latex)
    if not result.ok:
        raise _Unsupported("katex_parse_failed")
    if result.version != "0.17.0":
        raise _Unsupported("unvalidated_katex_version")
    return _sequence(result.ast), f"katex-{result.version}-raw-ast"


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
    difference = _difference(reference, candidate)
    return StructuralResult(
        "DIFFERENT" if difference else "MATCH",
        "whole_expression_differs" if difference else "whole_expression_matches",
        parser_backend=backend, candidate_tree_sha256=_hash(candidate),
        reference_tree_sha256=_hash(reference), first_difference=difference,
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
