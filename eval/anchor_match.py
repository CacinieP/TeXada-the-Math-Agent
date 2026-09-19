"""Semantic anchor matching for the golden set.

Flattens a LaTeX string into a token sequence over the Semantic Layer
(KaTeX AST -> SemanticUnit), then checks whether an anchor's tokens appear
as an ordered subsequence of the output's tokens.

Two deliberate normalizations absorb equivalent spellings:

- presentation delimiters: ``(``/``)``/``[``/``]``/``\\{``/``\\}`` symbols and
  role-less ``group`` nodes all canonicalize to ``paren``, so
  ``\\left(x+1\\right)`` matches ``(x+1)``;
- a small value map for bar/mid variants and common macro aliases
  (``\\lvert`` -> ``|``, ``\\leq`` -> ``\\le``, ...).

Everything else matches exactly on (kind, value), which is what makes
operator degradation (``\\iiint`` -> ``\\int``) detectable.
"""
from __future__ import annotations

from texada.semantic.parser import SemanticParser

_PARSER = SemanticParser()

_DELIMITERS = {"(", ")", "[", "]", "\\{", "\\}", "\\lbrace", "\\rbrace",
               "\\lbrack", "\\rbrack"}

_VALUE_MAP = {
    "\\lvert": "|",
    "\\rvert": "|",
    "\\vert": "|",
    "\\mid": "|",
    "\\leq": "\\le",
    "\\geq": "\\ge",
    "\\neq": "\\ne",
}


def _token(kind: str, value: str) -> str:
    if kind == "symbol":
        return _VALUE_MAP.get(value, value) or kind
    return f"{kind}:{value}" if value else kind


def flatten_tokens(latex: str) -> list[str]:
    doc = _PARSER.parse(latex)
    tokens: list[str] = []

    def walk(unit):
        if unit.kind == "group" and not unit.role:
            tokens.append("paren")
        elif unit.kind == "symbol" and unit.value in _DELIMITERS:
            tokens.append("paren")
        else:
            tokens.append(_token(unit.kind, unit.value))
        for child in unit.children:
            walk(child)

    walk(doc.root)
    return tokens


def _is_subsequence(small: list[str], big: list[str]) -> bool:
    it = iter(big)
    return all(any(s == b for b in it) for s in small)


def anchor_present(output_latex: str, anchor_latex: str) -> bool:
    if not anchor_latex.strip():
        return False
    return _is_subsequence(
        flatten_tokens(anchor_latex), flatten_tokens(output_latex)
    )
