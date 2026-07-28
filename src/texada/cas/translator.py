"""Whitelist translation from TeXada Semantic Units to SymPy core objects."""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from typing import Any

from texada.cas.model import (
    CASCapabilityUnavailable,
    CASTranslationError,
    TranslationFailure,
)
from texada.semantic.model import SemanticDocument, SemanticUnit

_INTEGER_RE = re.compile(r"[0-9]+")
_SYMBOL_RE = re.compile(r"[A-Za-z]")
_FUNCTIONS = frozenset({"sin", "cos", "exp", "log"})
_ASSUMPTION_KEYS = frozenset(
    {
        "real",
        "integer",
        "positive",
        "negative",
        "nonnegative",
        "nonpositive",
        "nonzero",
    }
)
_AMBIGUOUS_SYMBOLS = frozenset({"e", "i"})


@dataclass(frozen=True)
class TranslatedExpression:
    """A controlled SymPy object and its version-stable diagnostic form."""

    expression: Any
    srepr: str


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any
    path: str


class SemanticSymPyTranslator:
    """Translate only explicitly supported Semantic Unit shapes.

    No raw LaTeX is passed to ``sympify`` or ``parse_latex``. Unsupported
    notation is rejected before any algebraic comparison can run.
    """

    def __init__(
        self,
        *,
        assumptions: dict[str, dict[str, bool]] | None = None,
    ):
        self.assumptions = assumptions or {}
        self._validate_assumptions()
        self._sp: Any | None = None

    def translate_document(self, document: SemanticDocument) -> TranslatedExpression:
        if document.diagnostics:
            self._reject(
                "parse_diagnostics",
                "$",
                "semantic document has parse diagnostics",
            )
        if not document.parser_backend.startswith("katex-"):
            self._reject(
                "untrusted_parser_backend",
                "$",
                f"CAS translation requires KaTeX AST, got {document.parser_backend}",
            )
        expression = self._translate(document.root, "$")
        return TranslatedExpression(
            expression=expression,
            srepr=self.sp.srepr(expression),
        )

    @property
    def assumption_labels(self) -> list[str]:
        labels: list[str] = []
        for symbol in sorted(self.assumptions):
            for key in sorted(self.assumptions[symbol]):
                if self.assumptions[symbol][key]:
                    labels.append(f"{symbol} is {key}")
        return labels

    @property
    def sp(self) -> Any:
        if self._sp is None:
            try:
                self._sp = importlib.import_module("sympy")
            except ModuleNotFoundError as exc:
                raise CASCapabilityUnavailable(
                    "SymPy is not installed; install TeXada with the 'cas' extra"
                ) from exc
        return self._sp

    def _translate(self, unit: SemanticUnit, path: str) -> Any:
        if unit.kind in {"sequence", "group"}:
            return self._translate_sequence(unit.children, path)
        if unit.kind == "number":
            if not _INTEGER_RE.fullmatch(unit.value):
                self._reject(
                    "non_integer_literal",
                    path,
                    "v1 accepts integer literals; use an explicit fraction for rationals",
                )
            return self.sp.Integer(unit.value)
        if unit.kind == "symbol":
            return self._translate_symbol(unit.value, path)
        if unit.kind == "fraction":
            numerator = self._role_child(unit, "numerator", path)
            denominator = self._role_child(unit, "denominator", path)
            return self._translate(numerator, f"{path}.numerator") / self._translate(
                denominator,
                f"{path}.denominator",
            )
        if unit.kind == "root":
            radicand = self._role_child(unit, "radicand", path)
            index = next((child for child in unit.children if child.role == "index"), None)
            if index is None:
                degree = self.sp.Integer(2)
            else:
                degree = self._translate(index, f"{path}.index")
                if degree.is_Integer is not True or degree.is_positive is not True:
                    self._reject(
                        "unsupported_root_index",
                        f"{path}.index",
                        "root index must be a positive integer",
                    )
            return self.sp.Pow(
                self._translate(radicand, f"{path}.radicand"),
                self.sp.Rational(1, degree),
            )
        if unit.kind == "script":
            if any(child.role == "subscript" for child in unit.children):
                self._reject(
                    "subscript_notation",
                    path,
                    "subscripts are not yet mapped to CAS symbol identity",
                )
            base = self._role_child(unit, "base", path)
            exponent = self._role_child(unit, "superscript", path)
            return self.sp.Pow(
                self._translate(base, f"{path}.base"),
                self._translate(exponent, f"{path}.superscript"),
            )
        if unit.kind == "command" and unit.value in _FUNCTIONS:
            self._reject(
                "detached_function",
                path,
                f"function {unit.value} has no explicit argument",
            )
        if unit.kind == "integral":
            self._reject(
                "detached_integral",
                path,
                "integral must be the leading unit of a bounded integral sequence",
            )
        if unit.kind in {"summation", "product", "limit"}:
            self._reject(
                "unsupported_operator",
                path,
                f"{unit.kind} is outside the v1 algebra subset",
            )
        if unit.kind == "environment":
            self._reject(
                "structured_environment",
                path,
                f"{unit.value or 'environment'} is structural, not a scalar expression",
            )
        if unit.kind == "command":
            self._reject(
                "unsupported_command",
                path,
                f"command \\{unit.value} is not in the function whitelist",
            )
        if unit.kind == "katex_node":
            self._reject(
                "unsupported_katex_node",
                path,
                f"KaTeX node {unit.value or unit.attributes.get('katex_type')} is unsupported",
            )
        self._reject(
            "unsupported_semantic_unit",
            path,
            f"semantic kind {unit.kind} is not in the CAS whitelist",
        )

    def _translate_sequence(self, children: list[SemanticUnit], path: str) -> Any:
        if not children:
            self._reject("empty_expression", path, "expression has no semantic units")
        if children[0].kind == "integral":
            return self._translate_integral(children, path)
        if any(child.kind == "integral" for child in children):
            self._reject(
                "embedded_integral",
                path,
                "v1 accepts only a standalone bounded definite integral",
            )

        tokens = self._tokens(children, path)
        parser = _ExpressionParser(self, self._insert_implicit_multiplication(tokens))
        return parser.parse()

    def _translate_integral(self, children: list[SemanticUnit], path: str) -> Any:
        operator = children[0]
        lower = next((child for child in operator.children if child.role == "lower_bound"), None)
        upper = next((child for child in operator.children if child.role == "upper_bound"), None)
        if lower is None or upper is None:
            self._reject(
                "unbounded_integral",
                f"{path}[0]",
                "v1 accepts only integrals with finite explicit lower and upper bounds",
            )
        if len(children) < 4:
            self._reject(
                "missing_differential",
                path,
                "bounded integral must end in an explicit d followed by one variable",
            )
        differential = children[-2]
        variable = children[-1]
        if differential.kind != "symbol" or differential.value != "d":
            self._reject(
                "missing_differential",
                f"{path}[{len(children) - 2}]",
                "bounded integral must end in an explicit d followed by one variable",
            )
        if variable.kind != "symbol":
            self._reject(
                "unsupported_integration_variable",
                f"{path}[{len(children) - 1}]",
                "integration variable must be one explicit symbol",
            )
        variable_expr = self._translate_symbol(
            variable.value,
            f"{path}[{len(children) - 1}]",
        )
        integrand = self._translate_sequence(children[1:-2], f"{path}.integrand")
        lower_expr = self._translate(lower, f"{path}.lower_bound")
        upper_expr = self._translate(upper, f"{path}.upper_bound")
        for label, bound in (("lower", lower_expr), ("upper", upper_expr)):
            if bound.free_symbols or bound.is_finite is not True:
                self._reject(
                    "non_finite_integral_bound",
                    f"{path}.{label}_bound",
                    "integral bounds must be finite exact constants in v1",
                )
        return self.sp.Integral(
            integrand,
            (variable_expr, lower_expr, upper_expr),
        )

    def _tokens(self, children: list[SemanticUnit], path: str) -> list[_Token]:
        tokens: list[_Token] = []
        for index, unit in enumerate(children):
            unit_path = f"{path}[{index}]"
            if unit.kind == "symbol" and unit.value in {"+", "-", "*", "/", "="}:
                tokens.append(_Token("operator", unit.value, unit_path))
            elif unit.kind == "symbol" and unit.value == "(":
                tokens.append(_Token("left_parenthesis", unit.value, unit_path))
            elif unit.kind == "symbol" and unit.value == ")":
                tokens.append(_Token("right_parenthesis", unit.value, unit_path))
            elif unit.kind == "script" and self._is_powered_closing_parenthesis(unit):
                exponent = self._role_child(unit, "superscript", unit_path)
                tokens.append(
                    _Token(
                        "right_parenthesis",
                        {
                            "delimiter": ")",
                            "exponent": self._translate(
                                exponent,
                                f"{unit_path}.superscript",
                            ),
                        },
                        unit_path,
                    )
                )
            elif unit.kind == "command" and unit.value in _FUNCTIONS:
                tokens.append(_Token("function", unit.value, unit_path))
            else:
                tokens.append(_Token("atom", self._translate(unit, unit_path), unit_path))
        return tokens

    @staticmethod
    def _is_powered_closing_parenthesis(unit: SemanticUnit) -> bool:
        if any(child.role == "subscript" for child in unit.children):
            return False
        base = next((child for child in unit.children if child.role == "base"), None)
        exponent = next(
            (child for child in unit.children if child.role == "superscript"),
            None,
        )
        return (
            base is not None
            and base.kind == "symbol"
            and base.value == ")"
            and exponent is not None
        )

    @staticmethod
    def _insert_implicit_multiplication(tokens: list[_Token]) -> list[_Token]:
        expanded: list[_Token] = []
        left_kinds = {"atom", "right_parenthesis"}
        right_kinds = {"atom", "left_parenthesis", "function"}
        for token in tokens:
            if expanded and expanded[-1].kind in left_kinds and token.kind in right_kinds:
                expanded.append(_Token("operator", "*", token.path))
            expanded.append(token)
        return expanded

    def _translate_symbol(self, value: str, path: str) -> Any:
        if value == r"\pi":
            return self.sp.pi
        if value in _AMBIGUOUS_SYMBOLS:
            self._reject(
                "ambiguous_constant_symbol",
                path,
                f"{value!r} may mean a variable or a mathematical constant",
            )
        if not _SYMBOL_RE.fullmatch(value):
            self._reject(
                "unsupported_symbol",
                path,
                f"symbol {value!r} is outside the explicit ASCII symbol whitelist",
            )
        assumptions = self.assumptions.get(value, {})
        return self.sp.Symbol(value, **assumptions)

    def _validate_assumptions(self) -> None:
        for symbol, values in self.assumptions.items():
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"assumption symbol must be one ASCII letter: {symbol!r}")
            unknown = set(values) - _ASSUMPTION_KEYS
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(f"unsupported assumptions for {symbol}: {names}")
            if any(not isinstance(value, bool) for value in values.values()):
                raise TypeError(f"assumptions for {symbol} must be booleans")

    @staticmethod
    def _role_child(unit: SemanticUnit, role: str, path: str) -> SemanticUnit:
        child = next((item for item in unit.children if item.role == role), None)
        if child is None:
            raise CASTranslationError(
                TranslationFailure(
                    code="missing_semantic_role",
                    path=path,
                    detail=f"{unit.kind} has no {role} child",
                )
            )
        return child

    @staticmethod
    def _reject(code: str, path: str, detail: str) -> None:
        raise CASTranslationError(
            TranslationFailure(code=code, path=path, detail=detail)
        )


class _ExpressionParser:
    """Small Pratt-style parser over trusted semantic tokens, not source text."""

    def __init__(self, translator: SemanticSymPyTranslator, tokens: list[_Token]):
        self.translator = translator
        self.tokens = tokens
        self.position = 0

    def parse(self) -> Any:
        result = self._relation()
        if self.position != len(self.tokens):
            token = self.tokens[self.position]
            self.translator._reject(
                "unexpected_token",
                token.path,
                f"unexpected {token.kind} {token.value!r}",
            )
        return result

    def _relation(self) -> Any:
        left = self._additive()
        if not self._accept_operator("="):
            return left
        right = self._additive()
        if self._peek_operator("="):
            token = self.tokens[self.position]
            self.translator._reject(
                "chained_relation",
                token.path,
                "v1 accepts one equality per expression",
            )
        return self.translator.sp.Eq(left, right, evaluate=False)

    def _additive(self) -> Any:
        value = self._multiplicative()
        while True:
            if self._accept_operator("+"):
                value += self._multiplicative()
            elif self._accept_operator("-"):
                value -= self._multiplicative()
            else:
                return value

    def _multiplicative(self) -> Any:
        value = self._prefix()
        while True:
            if self._accept_operator("*"):
                value *= self._prefix()
            elif self._accept_operator("/"):
                value /= self._prefix()
            else:
                return value

    def _prefix(self) -> Any:
        if self._accept_operator("+"):
            return self._prefix()
        if self._accept_operator("-"):
            return -self._prefix()
        token = self._next()
        if token.kind == "atom":
            return token.value
        if token.kind == "function":
            if self._peek("left_parenthesis"):
                argument, exponent = self._parenthesized_parts()
                value = getattr(self.translator.sp, token.value)(argument)
                if exponent is not None:
                    value = self.translator.sp.Pow(value, exponent)
                return value
            return getattr(self.translator.sp, token.value)(self._prefix())
        if token.kind == "left_parenthesis":
            self.position -= 1
            value, exponent = self._parenthesized_parts()
            if exponent is not None:
                value = self.translator.sp.Pow(value, exponent)
            return value
        self.translator._reject(
            "expected_expression",
            token.path,
            f"expected an expression, got {token.kind} {token.value!r}",
        )

    def _parenthesized_parts(self) -> tuple[Any, Any | None]:
        opening = self._next()
        if opening.kind != "left_parenthesis":
            self.translator._reject(
                "expected_parenthesis",
                opening.path,
                "function argument must start with '('",
            )
        value = self._relation()
        closing = self._next()
        if closing.kind != "right_parenthesis":
            self.translator._reject(
                "unclosed_parenthesis",
                opening.path,
                "missing closing ')'",
            )
        exponent = (
            closing.value.get("exponent")
            if isinstance(closing.value, dict)
            else None
        )
        return value, exponent

    def _accept_operator(self, value: str) -> bool:
        if self._peek_operator(value):
            self.position += 1
            return True
        return False

    def _peek_operator(self, value: str) -> bool:
        return (
            self.position < len(self.tokens)
            and self.tokens[self.position].kind == "operator"
            and self.tokens[self.position].value == value
        )

    def _peek(self, kind: str) -> bool:
        return (
            self.position < len(self.tokens)
            and self.tokens[self.position].kind == kind
        )

    def _next(self) -> _Token:
        if self.position >= len(self.tokens):
            path = self.tokens[-1].path if self.tokens else "$"
            self.translator._reject(
                "unexpected_end",
                path,
                "expression ended before an operand was found",
            )
        token = self.tokens[self.position]
        self.position += 1
        return token
