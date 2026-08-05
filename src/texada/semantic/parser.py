"""Map a KaTeX syntax tree into TeXada semantic math units.

KaTeX runs inside a reusable in-process V8 context. A small tolerant parser is
kept only as a recovery path for malformed input and unsupported custom macros.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from texada.semantic.katex import (
    MAX_NESTING_DEPTH,
    max_nesting_depth,
    shared_katex_parser,
)
from texada.semantic.model import SemanticDocument, SemanticUnit

_OPERATOR_KINDS = {
    "int": "integral",
    "iint": "integral",
    "iiint": "integral",
    "oint": "integral",
    "sum": "summation",
    "prod": "product",
    "lim": "limit",
}
_ARGUMENT_COMMANDS = {
    "text",
    "mathrm",
    "mathbf",
    "mathcal",
    "mathbb",
    "mathscr",
    "operatorname",
    "overline",
    "underline",
    "hat",
    "bar",
    "vec",
}


class SemanticParser:
    """Parse common LaTeX math structures into semantic units."""

    def __init__(self, *, use_katex: bool = True):
        self.use_katex = use_katex

    def parse(self, latex: str) -> SemanticDocument:
        # Pre-flight structural guard: deeply nested input can hang or crash
        # the in-process V8/KaTeX parser and overflows every recursive layer
        # (mapper, tolerant fallback, serializers). Refuse it before any
        # recursion happens.
        if max_nesting_depth(latex) > MAX_NESTING_DEPTH:
            return SemanticDocument(
                latex=latex,
                root=SemanticUnit(kind="sequence"),
                diagnostics=[
                    f"maximum nesting depth exceeded (limit {MAX_NESTING_DEPTH})"
                ],
                parser_backend="depth-guard",
            )
        if self.use_katex:
            try:
                result = shared_katex_parser().parse(latex)
                if result.ok:
                    root = _KaTeXSemanticMapper(latex).map_tree(result.ast)
                    return SemanticDocument(
                        latex=latex,
                        root=root,
                        parser_backend=f"katex-{result.version}-v8",
                    )
                katex_error = result.error
            except Exception as exc:
                katex_error = f"KaTeX bridge unavailable: {exc}"
        else:
            katex_error = ""

        state = _ParserState(latex)
        try:
            root = state.parse_sequence()
        except RecursionError:
            # Defense in depth: the tolerant parser is recursive too.
            root = SemanticUnit(kind="sequence")
            state.diagnostics.append("tolerant parser exceeded recursion depth")
        diagnostics = list(state.diagnostics)
        if katex_error:
            diagnostics.insert(0, katex_error)
        return SemanticDocument(
            latex=latex,
            root=root,
            diagnostics=diagnostics,
            parser_backend="tolerant-fallback",
        )


class _KaTeXSemanticMapper:
    """Reduce KaTeX's presentation AST to stable, domain-specific units."""

    _PRESENTATION_WRAPPERS = {
        "styling",
        "sizing",
        "color",
        "mclass",
        "phantom",
        "hphantom",
        "vphantom",
        "smash",
        "raisebox",
    }
    _IGNORED = {"kern", "spacing", "cr", "rule"}

    def __init__(self, source: str):
        self.source = source

    def map_tree(self, ast: list[dict[str, Any]]) -> SemanticUnit:
        return SemanticUnit(
            kind="sequence",
            children=self._map_nodes(ast),
            source=self.source,
        )

    def _map_nodes(self, nodes: Any) -> list[SemanticUnit]:
        if not isinstance(nodes, list):
            node = self._map_node(nodes)
            return [node] if node else []
        units: list[SemanticUnit] = []
        for item in nodes:
            if isinstance(item, list):
                units.extend(self._map_nodes(item))
                continue
            unit = self._map_node(item)
            if unit is not None:
                units.append(unit)
        return units

    def _map_node(self, node: Any) -> SemanticUnit | None:
        if not isinstance(node, dict):
            return None
        node_type = str(node.get("type") or "unknown")
        source = self._source(node)

        if node_type in self._IGNORED:
            return None
        if node_type == "genfrac":
            return SemanticUnit(
                kind="fraction",
                value="frac",
                children=[
                    self._argument(node.get("numer"), "numerator"),
                    self._argument(node.get("denom"), "denominator"),
                ],
                source=source,
            )
        if node_type == "sqrt":
            children: list[SemanticUnit] = []
            if node.get("index") is not None:
                children.append(self._argument(node["index"], "index"))
            children.append(self._argument(node.get("body"), "radicand"))
            return SemanticUnit(
                kind="root",
                value="sqrt",
                children=children,
                source=source,
            )
        if node_type == "supsub":
            base = self._map_node(node.get("base")) or SemanticUnit(kind="missing")
            sub = node.get("sub")
            sup = node.get("sup")
            if base.kind in set(_OPERATOR_KINDS.values()):
                children = list(base.children)
                if sub is not None:
                    children.append(self._argument(sub, "lower_bound"))
                if sup is not None:
                    children.append(self._argument(sup, "upper_bound"))
                return replace(base, children=children, source=source)
            children = [replace(base, role="base")]
            if sub is not None:
                children.append(self._argument(sub, "subscript"))
            if sup is not None:
                children.append(self._argument(sup, "superscript"))
            return SemanticUnit(kind="script", children=children, source=source)
        if node_type == "op":
            name = str(node.get("name") or "").lstrip("\\")
            if name in _OPERATOR_KINDS:
                return SemanticUnit(
                    kind=_OPERATOR_KINDS[name],
                    value=name,
                    source=source,
                )
            body = self._map_nodes(node.get("body"))
            return SemanticUnit(
                kind="command",
                value=name or "operator",
                children=body,
                source=source,
            )
        if node_type == "ordgroup":
            return SemanticUnit(
                kind="group",
                children=self._map_nodes(node.get("body")),
                source=source,
            )
        if node_type == "array":
            rows: list[SemanticUnit] = []
            for row_index, row in enumerate(node.get("body") or []):
                cells = [
                    SemanticUnit(
                        kind="cell",
                        role=f"column_{column_index}",
                        children=self._map_nodes(cell),
                    )
                    for column_index, cell in enumerate(row)
                ]
                rows.append(
                    SemanticUnit(
                        kind="row",
                        role=f"row_{row_index}",
                        children=cells,
                    )
                )
            return SemanticUnit(
                kind="environment",
                value="array",
                children=rows,
                source=source,
            )
        if node_type == "leftright":
            children = self._map_nodes(node.get("body"))
            attributes = {
                "left_delimiter": node.get("left"),
                "right_delimiter": node.get("right"),
            }
            if len(children) == 1 and children[0].kind == "environment":
                return replace(
                    children[0],
                    value="matrix",
                    attributes=attributes,
                    source=source,
                )
            return SemanticUnit(
                kind="group",
                children=children,
                attributes=attributes,
                source=source,
            )
        if node_type == "font":
            font = str(node.get("font") or "font")
            return SemanticUnit(
                kind="command",
                value=font,
                children=self._map_nodes(node.get("body")),
                source=source,
            )
        if node_type in self._PRESENTATION_WRAPPERS:
            children = self._map_nodes(node.get("body"))
            if len(children) == 1:
                return children[0]
            return SemanticUnit(kind="sequence", children=children, source=source)
        if node_type in {"accent", "accentUnder", "overline", "underline"}:
            label = str(node.get("label") or node_type).lstrip("\\")
            return SemanticUnit(
                kind="command",
                value=label,
                children=[self._argument(node.get("base"), "argument")],
                source=source,
            )
        if node_type in {"mathord", "textord", "atom"}:
            text = str(node.get("text") or "")
            kind = "number" if self._is_number(text) else "symbol"
            return SemanticUnit(kind=kind, value=text, source=source or text)

        children: list[SemanticUnit] = []
        for key in ("body", "base", "numer", "denom", "index"):
            if key in node:
                children.extend(self._map_nodes(node[key]))
        value = str(node.get("name") or node.get("label") or node_type).lstrip("\\")
        return SemanticUnit(
            kind="katex_node",
            value=value,
            children=children,
            attributes={"katex_type": node_type},
            source=source,
        )

    def _argument(self, node: Any, role: str) -> SemanticUnit:
        mapped = self._map_node(node)
        if mapped is None:
            return SemanticUnit(kind="missing", role=role)
        return replace(mapped, role=role)

    def _source(self, node: dict[str, Any]) -> str:
        loc = node.get("loc")
        if not isinstance(loc, dict):
            return ""
        start = loc.get("start")
        end = loc.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return ""
        if start < 0 or end < start or end > len(self.source):
            return ""
        return self.source[start:end]

    @staticmethod
    def _is_number(text: str) -> bool:
        try:
            float(text)
        except ValueError:
            return False
        return bool(text)


class _ParserState:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.diagnostics: list[str] = []

    def parse_sequence(self, stop: str | None = None) -> SemanticUnit:
        start = self.pos
        children: list[SemanticUnit] = []
        while self.pos < len(self.source):
            if stop and self.source.startswith(stop, self.pos):
                break
            ch = self.source[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            if ch == "\\":
                children.append(self._parse_command())
                continue
            if ch == "{":
                children.append(self._parse_group())
                continue
            if ch in {"_", "^"} and children:
                marker = ch
                self.pos += 1
                argument = self._parse_argument("subscript" if marker == "_" else "superscript")
                base = replace(children.pop(), role="base")
                children.append(
                    SemanticUnit(
                        kind="script",
                        children=[base, argument],
                        source=f"{base.source}{marker}{argument.source}",
                    )
                )
                continue
            children.append(self._parse_symbol())
        return SemanticUnit(
            kind="sequence",
            children=children,
            source=self.source[start : self.pos],
        )

    def _parse_command(self) -> SemanticUnit:
        start = self.pos
        self.pos += 1
        match = re.match(r"[A-Za-z]+", self.source[self.pos :])
        if match:
            name = match.group(0)
            self.pos += len(name)
        elif self.pos < len(self.source):
            name = self.source[self.pos]
            self.pos += 1
        else:
            name = ""

        if name == "frac":
            numerator = self._parse_argument("numerator")
            denominator = self._parse_argument("denominator")
            return SemanticUnit(
                kind="fraction",
                value="frac",
                children=[numerator, denominator],
                source=self.source[start : self.pos],
            )
        if name == "sqrt":
            children: list[SemanticUnit] = []
            if self.pos < len(self.source) and self.source[self.pos] == "[":
                children.append(self._parse_bracket_argument("index"))
            children.append(self._parse_argument("radicand"))
            return SemanticUnit(
                kind="root",
                value="sqrt",
                children=children,
                source=self.source[start : self.pos],
            )
        if name == "begin":
            return self._parse_environment(start)
        if name in _OPERATOR_KINDS:
            children = self._parse_limits()
            return SemanticUnit(
                kind=_OPERATOR_KINDS[name],
                value=name,
                children=children,
                source=self.source[start : self.pos],
            )
        if name in _ARGUMENT_COMMANDS:
            argument = self._parse_argument("argument")
            return SemanticUnit(
                kind="command",
                value=name,
                children=[argument],
                source=self.source[start : self.pos],
            )
        if name in {"left", "right"}:
            delimiter = ""
            if self.pos < len(self.source):
                delimiter = self.source[self.pos]
                self.pos += 1
            return SemanticUnit(
                kind="delimiter",
                value=f"{name}:{delimiter}",
                source=self.source[start : self.pos],
            )
        return SemanticUnit(
            kind="command",
            value=name,
            source=self.source[start : self.pos],
        )

    def _parse_environment(self, start: int) -> SemanticUnit:
        env_arg = self._parse_argument("environment_name")
        env_name = self._plain_text(env_arg)
        end_marker = f"\\end{{{env_name}}}" if env_name else ""
        if not end_marker:
            self.diagnostics.append("Missing environment name after \\begin")
            return SemanticUnit(
                kind="environment",
                value="",
                children=[],
                source=self.source[start : self.pos],
            )

        end = self.source.find(end_marker, self.pos)
        if end < 0:
            inner_source = self.source[self.pos :]
            self.pos = len(self.source)
            self.diagnostics.append(f"Missing {end_marker}")
        else:
            inner_source = self.source[self.pos : end]
            self.pos = end + len(end_marker)

        inner_state = _ParserState(inner_source)
        inner = inner_state.parse_sequence()
        self.diagnostics.extend(inner_state.diagnostics)
        return SemanticUnit(
            kind="environment",
            value=env_name,
            children=[replace(inner, role="body")],
            source=self.source[start : self.pos],
        )

    def _parse_limits(self) -> list[SemanticUnit]:
        children: list[SemanticUnit] = []
        while True:
            saved = self.pos
            while self.pos < len(self.source) and self.source[self.pos].isspace():
                self.pos += 1
            if self.pos >= len(self.source) or self.source[self.pos] not in {"_", "^"}:
                self.pos = saved
                break
            marker = self.source[self.pos]
            self.pos += 1
            children.append(self._parse_argument("lower_bound" if marker == "_" else "upper_bound"))
        return children

    def _parse_argument(self, role: str) -> SemanticUnit:
        while self.pos < len(self.source) and self.source[self.pos].isspace():
            self.pos += 1
        if self.pos >= len(self.source):
            self.diagnostics.append(f"Missing {role} argument")
            return SemanticUnit(kind="missing", role=role)
        if self.source[self.pos] == "{":
            return replace(self._parse_group(), role=role)
        if self.source[self.pos] == "\\":
            return replace(self._parse_command(), role=role)
        return replace(self._parse_symbol(), role=role)

    def _parse_group(self) -> SemanticUnit:
        start = self.pos
        self.pos += 1
        body = self.parse_sequence(stop="}")
        if self.pos < len(self.source) and self.source[self.pos] == "}":
            self.pos += 1
        else:
            self.diagnostics.append(f"Unclosed group at position {start}")
        return SemanticUnit(
            kind="group",
            children=body.children,
            source=self.source[start : self.pos],
        )

    def _parse_bracket_argument(self, role: str) -> SemanticUnit:
        start = self.pos
        self.pos += 1
        inner_start = self.pos
        while self.pos < len(self.source) and self.source[self.pos] != "]":
            self.pos += 1
        inner = self.source[inner_start : self.pos]
        if self.pos < len(self.source):
            self.pos += 1
        else:
            self.diagnostics.append(f"Unclosed bracket at position {start}")
        inner_state = _ParserState(inner)
        parsed = inner_state.parse_sequence()
        self.diagnostics.extend(inner_state.diagnostics)
        return SemanticUnit(
            kind="group",
            role=role,
            children=parsed.children,
            source=self.source[start : self.pos],
        )

    def _parse_symbol(self) -> SemanticUnit:
        start = self.pos
        ch = self.source[self.pos]
        if ch.isdigit():
            while self.pos < len(self.source) and (
                self.source[self.pos].isdigit() or self.source[self.pos] == "."
            ):
                self.pos += 1
            kind = "number"
        else:
            self.pos += 1
            kind = "symbol"
        value = self.source[start : self.pos]
        return SemanticUnit(kind=kind, value=value, source=value)

    def _plain_text(self, unit: SemanticUnit) -> str:
        if unit.value:
            return unit.value
        return "".join(self._plain_text(child) for child in unit.children)
