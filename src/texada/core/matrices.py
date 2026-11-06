"""Bounded matrix parameters, initial candidates, and structural evidence."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from texada.core.inference_fingerprint import canonical_sha256
from texada.semantic.katex import MAX_NESTING_DEPTH, KaTeXParseResult, shared_katex_parser
from texada.semantic.structure import (
    NORMALIZATION_VERSION,
    UnsupportedStructure,
    canonical_structure,
)

_GREEK = (
    "alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|"
    "kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|"
    "phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega"
)
_BASE = rf"(?:[A-Za-z]|\\(?:{_GREEK}))"
_ENTRY = re.compile(rf"(?P<base>{_BASE})(?P<index>i|_i|_\{{i\}})?")
_CONSTANT = re.compile(r"[-+]?\d+(?:\.\d+)?")
_ORDER = r"(?:\d+|[A-Za-z]|[一二三四五六七八九十]+)"
_PREFIX = r"(?:(?:写(?:出)?|生成|给我)(?:一个|个)?)?"
_HEADER = re.compile(
    rf"{_PREFIX}(?:(?P<order>{_ORDER})阶)?(?P<kind>三对角)?矩阵"
)
_RECTANGLE = re.compile(
    rf"{_PREFIX}(?:通用)?(?P<rows>{_ORDER})行(?P<columns>{_ORDER})列矩阵"
)
_DIAGONAL = re.compile(r"(?P<role>主|上|下)(?:次)?对角线(?:是|为)(?P<value>.+)")
_CHINESE_ORDERS = {name: number for number, name in enumerate("一二三四五六七八九", 1)}
_CHINESE_ORDERS.update({"十": 10, "二十": 20})
_CHINESE_ORDERS.update({f"十{name}": number + 10
                        for name, number in list(_CHINESE_ORDERS.items()) if number < 10})
_VDOTS_EXPANSION = {
    "type": "ordgroup", "mode": "math", "body": [
        {"type": "textord", "mode": "math", "text": r"\varvdots"},
        {"type": "rule", "mode": "math", "shift": None,
         "width": {"number": 0, "unit": "pt"}, "height": {"number": 15, "unit": "pt"}},
    ],
}
_VDOTS_EXPANSION_SHA256 = canonical_sha256(_VDOTS_EXPANSION)


class MatrixSpec(BaseModel):
    """Validated parameters shared by presets and recognized descriptions."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["general", "tridiagonal"] = "general"
    rows: int | str = 3
    columns: int | str = 3
    element: str = "a"
    diagonal: str = "a_i"
    upper: str = "b_i"
    lower: str = "c_i"
    bracket: Literal["pmatrix", "bmatrix", "matrix", "vmatrix"] = "pmatrix"
    display: Literal["expanded", "compact"] = "expanded"
    index_start: Literal[0, 1] = 1

    @field_validator("rows", "columns", mode="before")
    @classmethod
    def validate_dimension(cls, value: object) -> int | str:
        if type(value) is int and 1 <= value <= 20:
            return value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z]", value):
            return value
        raise ValueError("matrix dimensions must be integers from 1 to 20 or single letters")

    @field_validator("index_start", mode="before")
    @classmethod
    def validate_index_start(cls, value: object) -> int:
        if type(value) is int and value in {0, 1}:
            return value
        raise ValueError("matrix index origin must be the integer 0 or 1")

    @field_validator("element")
    @classmethod
    def validate_element(cls, value: str) -> str:
        value = value.strip()
        if re.fullmatch(_BASE, value):
            return value
        raise ValueError("matrix element must be a single letter or Greek command")

    @field_validator("diagonal", "upper", "lower")
    @classmethod
    def validate_entry(cls, value: str) -> str:
        value = value.strip()
        if len(value) <= 64 and _CONSTANT.fullmatch(value):
            return value
        entry = _ENTRY.fullmatch(value)
        if entry:
            return entry["base"] + ("_i" if entry["index"] else "")
        raise ValueError(
            "diagonal entries must be numeric constants or simple symbols with index i"
        )

    @model_validator(mode="after")
    def validate_shape(self) -> MatrixSpec:
        if self.kind == "tridiagonal" and self.rows != self.columns:
            raise ValueError("tridiagonal matrices must have matching row and column dimensions")
        if isinstance(self.rows, str) or isinstance(self.columns, str):
            object.__setattr__(self, "display", "compact")
        return self


def _end_index(dimension: int | str, start: int, offset: int = 0) -> int | str:
    difference = start - 1 + offset
    if isinstance(dimension, int):
        return dimension + difference
    if difference == 0:
        return dimension
    return f"{dimension}{difference:+d}"


def _positions(dimension: int | str, start: int, display: str) -> list[int | str | None]:
    if isinstance(dimension, int) and (display == "expanded" or dimension <= 5):
        return list(range(start, start + dimension))
    return [start, start + 1, None,
            _end_index(dimension, start, -1), _end_index(dimension, start)]


def _entry(expression: str, index: int | str) -> str:
    if expression.endswith("_i"):
        return expression[:-2] + f"_{{{index}}}"
    return expression


def generate_matrix(spec: MatrixSpec) -> str:
    """Produce a bounded display with explicit concrete or logical dimensions."""
    start = spec.index_start
    if spec.kind == "tridiagonal" and (
        isinstance(spec.rows, str) or spec.display == "compact" and spec.rows > 5
    ):
        last = _end_index(spec.rows, start)
        penultimate = _end_index(spec.rows, start, -1)
        preceding = _end_index(spec.rows, start, -2)
        rows = [
            [_entry(spec.diagonal, start), _entry(spec.upper, start), "0", r"\cdots", "0"],
            [_entry(spec.lower, start), _entry(spec.diagonal, start + 1),
             _entry(spec.upper, start + 1), r"\ddots", r"\vdots"],
            ["0", r"\ddots", r"\ddots", r"\ddots", "0"],
            [r"\vdots", r"\ddots", _entry(spec.lower, preceding),
             _entry(spec.diagonal, penultimate), _entry(spec.upper, penultimate)],
            ["0", r"\cdots", "0", _entry(spec.lower, penultimate), _entry(spec.diagonal, last)],
        ]
    elif spec.kind == "tridiagonal":
        rows = []
        for row in range(start, start + spec.rows):
            cells = []
            for column in range(start, start + spec.columns):
                if row == column:
                    cells.append(_entry(spec.diagonal, row))
                elif column == row + 1:
                    cells.append(_entry(spec.upper, row))
                elif row == column + 1:
                    cells.append(_entry(spec.lower, column))
                else:
                    cells.append("0")
            rows.append(cells)
    else:
        rows = []
        for row in _positions(spec.rows, start, spec.display):
            cells = []
            for column in _positions(spec.columns, start, spec.display):
                if row is None and column is None:
                    cells.append(r"\ddots")
                elif row is None:
                    cells.append(r"\vdots")
                elif column is None:
                    cells.append(r"\cdots")
                else:
                    cells.append(f"{spec.element}_{{{row},{column}}}")
            rows.append(cells)
    body = " \\\\\n".join(" & ".join(row) for row in rows)
    abbreviated = spec.display == "compact" and any(
        isinstance(dimension, str) or dimension > 5 for dimension in (spec.rows, spec.columns)
    )
    dimensions = f"_{{{spec.rows}\\times {spec.columns}}}" if abbreviated else ""
    return f"\\begin{{{spec.bracket}}}\n{body}\n\\end{{{spec.bracket}}}{dimensions}"


def _order(value: str) -> int | str:
    if value.isascii() and value.isdigit():
        return int(value)
    return _CHINESE_ORDERS.get(value, value)


def recognize_matrix(text: str) -> MatrixSpec | None:
    """Recognize complete, finite descriptions before symbol substitution."""
    text = re.sub(r"\s+", "", text).strip("。.!！?？")
    text = text.replace("，", ",")
    rectangle = _RECTANGLE.fullmatch(text)
    if rectangle:
        try:
            return MatrixSpec(rows=_order(rectangle["rows"]),
                              columns=_order(rectangle["columns"]))
        except ValueError:
            return None

    header, separator, description = text.partition(",")
    match = _HEADER.fullmatch(header)
    if not match:
        return None
    kind = "tridiagonal" if match["kind"] or separator else "general"
    if not match["order"] and not match["kind"] and not separator:
        return None
    order = _order(match["order"]) if match["order"] else "n"
    entries: dict[str, str] = {}
    if separator:
        paired = re.fullmatch(
            r"主对角线(?:是|为)(.+),两条次对角线(?:分别是|分别为)(.+),(.+)",
            description,
        )
        if paired:
            entries = dict(zip(("diagonal", "upper", "lower"), paired.groups(), strict=True))
        else:
            parts = description.split(",")
            roles = {"主": "diagonal", "上": "upper", "下": "lower"}
            for part in parts:
                diagonal = _DIAGONAL.fullmatch(part)
                if not diagonal or roles[diagonal["role"]] in entries:
                    return None
                entries[roles[diagonal["role"]]] = diagonal["value"]
            if entries.keys() != {"diagonal", "upper", "lower"}:
                return None
    try:
        return MatrixSpec(kind=kind, rows=order, columns=order, **entries)
    except ValueError:
        return None


def _first_difference(expected: Any, candidate: Any, path: str = "matrix") -> str | None:
    if type(expected) is not type(candidate):
        return path
    if isinstance(expected, dict):
        if expected.keys() != candidate.keys():
            return path
        for key, value in expected.items():
            difference = _first_difference(value, candidate[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(expected, list):
        if len(expected) != len(candidate):
            return path + ".length"
        for index, (left, right) in enumerate(zip(expected, candidate, strict=True)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
    elif expected != candidate:
        return path
    return None


def _matrix_display_ast(value: Any, depth: int = 0) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise UnsupportedStructure("matrix_display_depth_limit")
    if isinstance(value, dict):
        normalized = {key: _matrix_display_ast(item, depth + 1)
                      for key, item in value.items() if key != "loc"}
        # KaTeX 0.18.2 expands portable \vdots into one symbol and one exact
        # zero-width spacing rule. Only that entire pinned expansion is known.
        if (normalized == _VDOTS_EXPANSION
                and canonical_sha256(normalized) == _VDOTS_EXPANSION_SHA256):
            return _VDOTS_EXPANSION["body"][0]
        return normalized
    if isinstance(value, list):
        return [_matrix_display_ast(item, depth + 1) for item in value]
    return value


class _MatrixDisplayParser:
    @staticmethod
    def parse(latex: str) -> KaTeXParseResult:
        result = shared_katex_parser().parse(latex)
        if result.version != "0.18.2":
            raise UnsupportedStructure("unvalidated_matrix_display_version")
        return replace(result, ast=_matrix_display_ast(result.ast))


def check_matrix(spec: MatrixSpec, latex: str) -> dict[str, Any]:
    """Check actual candidate structure against the supported display contract."""
    result: dict[str, Any] = {
        "verdict": "NOT_CHECKED",
        "spec": spec.model_dump(),
        "coverage": {
            "scope": "canonical_matrix_display",
            "display": spec.display,
            "logical_rows": spec.rows,
            "logical_columns": spec.columns,
            "dot_normalization": "katex-0.18.2-vdots-expansion",
            "checks": ["dimensions", "element_indices", "bracket", "display_contract"],
        },
        "normalization_version": f"matrix-display-v1/{NORMALIZATION_VERSION}",
        "diagnostics": [],
    }
    if spec.kind == "tridiagonal":
        result["coverage"]["checks"].extend(
            ["diagonal_expressions", "direction", "band_exterior_zeros"]
        )
    if not isinstance(latex, str) or not latex.strip():
        result["diagnostics"] = ["matrix candidate is unavailable"]
        return result
    try:
        parser = _MatrixDisplayParser()
        expected, backend = canonical_structure(generate_matrix(spec), parser=parser)
        candidate, backend = canonical_structure(latex, parser=parser)
    except UnsupportedStructure as exc:
        result.update(verdict="UNSUPPORTED", diagnostics=[str(exc)])
        return result
    except Exception:
        result.update(verdict="UNSUPPORTED", diagnostics=["matrix parser unavailable"])
        return result
    difference = _first_difference(expected, candidate)
    result.update(
        verdict="DIFFERENT" if difference else "MATCH",
        parser_backend=backend,
        candidate_tree_sha256=canonical_sha256(candidate),
        expected_tree_sha256=canonical_sha256(expected),
        first_difference=difference,
        diagnostics=[f"matrix display differs at {difference}"] if difference else [],
    )
    return result
