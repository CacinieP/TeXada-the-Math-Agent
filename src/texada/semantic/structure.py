"""Pinned raw AST structure for conservative evaluation and mutation scopes.

Unsupported presentation and macros are rejected, rather than compared through
the deliberately tolerant and lossy SemanticUnit projection.
"""
from __future__ import annotations

import re
from typing import Any

from texada.semantic.katex import MAX_NESTING_DEPTH, shared_katex_parser

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


class UnsupportedStructure(ValueError):
    pass


def _check_node(node: dict) -> None:
    kind = node.get("type")
    if kind not in _FIELDS:
        raise UnsupportedStructure(f"unsupported_katex_type:{kind or 'unknown'}")
    if node.get("mode", "math") != "math":
        raise UnsupportedStructure(f"non_math_mode:{kind}")
    extra = node.keys() - (_FIELDS[kind] | {"type", "mode", "loc"})
    if extra:
        raise UnsupportedStructure(f"unsupported_katex_fields:{kind}:{','.join(sorted(extra))}")


def _delimiter(value: Any) -> str:
    if not isinstance(value, str):
        raise UnsupportedStructure("missing_delimiter")
    return _DELIMITERS.get(value, value)


def _argument(node: Any, role: str, depth: int) -> dict:
    if node is None:
        raise UnsupportedStructure(f"missing_{role}")
    children = _sequence(node, depth + 1)
    if not children:
        raise UnsupportedStructure(f"empty_{role}")
    return {"role": role, "children": children}


def _scripts(node: dict, base: list[dict], depth: int) -> dict:
    if not base:
        raise UnsupportedStructure("empty_script_base")
    operator = len(base) == 1 and base[0].get("value") in _OPERATOR_ROLES
    children = [{"role": "base", "children": base}]
    for key, role in (("sub", "lower_bound" if operator else "subscript"),
                      ("sup", "upper_bound" if operator else "superscript")):
        if node.get(key) is not None:
            children.append(_argument(node[key], role, depth))
    return {"kind": "script", "children": children}


def _sequence(nodes: Any, depth: int = 0) -> list[dict]:
    if depth > MAX_NESTING_DEPTH:
        raise UnsupportedStructure("canonical_depth_limit")
    if isinstance(nodes, dict):
        nodes = [nodes]
    if not isinstance(nodes, list):
        raise UnsupportedStructure("malformed_ast_children")
    result: list[dict] = []
    stack: list[tuple[str, list[dict]]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise UnsupportedStructure("malformed_ast_node")
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
                    raise UnsupportedStructure("script_on_open_delimiter")
                if depth + len(stack) >= MAX_NESTING_DEPTH:
                    raise UnsupportedStructure("canonical_depth_limit")
                stack.append((delimiter, result))
                result = []
            else:
                if not stack:
                    raise UnsupportedStructure("unmatched_close_delimiter")
                left, parent = stack.pop()
                group = {"kind": "delimited", "left": left, "right": delimiter,
                         "children": result}
                parent.append(_scripts(node, [group], depth + len(stack) + 1)
                              if closing_script else group)
                result = parent
            continue
        result.extend(_node(node, depth + len(stack) + 1))
    if stack:
        raise UnsupportedStructure("unmatched_open_delimiter")
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
            raise UnsupportedStructure("empty_atom")
        if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value):
            raise UnsupportedStructure("non_formula_text_atom")
        # Keep symbol order and type; no commutativity, arithmetic, or CAS.
        return [{"kind": "symbol", "value": _SYMBOL_ALIASES.get(value, value)}]
    if kind == "supsub":
        return [_scripts(node, _sequence(node.get("base"), depth), depth)]
    if kind == "genfrac":
        if node.get("continued") or node.get("barSize") is not None:
            raise UnsupportedStructure("custom_fraction_presentation")
        if not isinstance(node.get("hasBarLine"), bool):
            raise UnsupportedStructure("missing_fraction_bar_contract")
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
            raise UnsupportedStructure("custom_operator")
        return [{"kind": "operator", "value": name}]
    if kind == "leftright":
        return [{"kind": "delimited", "left": _delimiter(node.get("left")),
                 "right": _delimiter(node.get("right")),
                 "children": _sequence(node.get("body"), depth)}]
    if kind == "array":
        if any(node.get("hLinesBeforeRow") or []):
            raise UnsupportedStructure("array_partition_lines")
        columns = node.get("cols") or []
        if any(not isinstance(c, dict) or c.get("type") != "align" for c in columns):
            raise UnsupportedStructure("array_column_partition")
        rows = node.get("body")
        if not isinstance(rows, list) or not rows or any(not isinstance(r, list) for r in rows):
            raise UnsupportedStructure("malformed_array")
        width = len(rows[0])
        if not width or any(len(row) != width for row in rows):
            raise UnsupportedStructure("ragged_array")
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
    raise UnsupportedStructure(f"unsupported_katex_type:{kind or 'unknown'}")


def canonical_structure(latex: str, *, parser: Any = None) -> tuple[list[dict], str]:
    if len(latex) > MAX_EXPRESSION_CHARS:
        raise UnsupportedStructure("expression_size_limit")
    if _SOURCE_GUARD.search(latex):
        raise UnsupportedStructure("unresolved_hole_or_custom_macro_definition")
    result = (parser or shared_katex_parser()).parse(latex)
    if not result.ok:
        raise UnsupportedStructure("katex_parse_failed")
    if result.version != "0.17.0":
        raise UnsupportedStructure("unvalidated_katex_version")
    return _sequence(result.ast), f"katex-{result.version}-raw-ast"


