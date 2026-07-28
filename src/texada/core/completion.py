"""Deterministic LaTeX completion for syntax holes and safe command typos."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DeterministicCompletion:
    """A zero-model completion that preserves the user's existing formula."""

    latex: str
    rule: str


class DeterministicCompletionEngine:
    """Fill unambiguous syntax holes before considering model inference.

    The engine deliberately inserts ``\\placeholder{}`` when mathematical
    content is unknown. It must never invent a bound, exponent, subscript, or
    right-hand side merely to make an expression parse.
    """

    _TAIL_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
        (re.compile(pattern), suffix, rule)
        for pattern, suffix, rule in (
            (r"\\alp$", "ha", "command_prefix"),
            (r"\\bet$", "a", "command_prefix"),
            (r"\\gam$", "ma", "command_prefix"),
            (r"\\del$", "ta", "command_prefix"),
            (r"\\the$", "ta", "command_prefix"),
            (r"\\lam$", "bda", "command_prefix"),
            (r"\\sig$", "ma", "command_prefix"),
            (r"\\ome$", "ga", "command_prefix"),
            (r"\\part$", "ial", "command_prefix"),
            (r"\\sum_\{i=1\}\^\{$", "n} x_i", "sum_prefix"),
            (r"\\sum_\{$", "i=1}^{n} x_i", "sum_prefix"),
            (r"\\sum$", "_{i=1}^{n} x_i", "sum_prefix"),
            (r"\\prod_\{$", "i=1}^{n} x_i", "product_prefix"),
            (r"\\prod$", "_{i=1}^{n} x_i", "product_prefix"),
            (
                r"\\frac\{$",
                r"\placeholder{}}{\placeholder{}}",
                "fraction_prefix",
            ),
            (r"\\sqrt\{$", r"\placeholder{}}", "root_prefix"),
            (r"\\int$", r"_{0}^{1} f(x)\,dx", "integral_prefix"),
            (r"\\int_\{$", r"0}^{1} f(x)\,dx", "integral_prefix"),
            (r"\\lim$", r"_{x \to 0}", "limit_prefix"),
            (r"\\lim_\{$", r"x \to 0}", "limit_prefix"),
            (r"\\mathbb\{$", "R}", "font_prefix"),
            (r"\\mathcal\{$", "L}", "font_prefix"),
            (r"\\operatorname\{ran$", "k}", "operatorname_prefix"),
            (r"\^\{$", r"\placeholder{}}", "superscript_brace"),
            (r"_\{$", r"\placeholder{}}", "subscript_brace"),
            (r"\{$", r"\placeholder{}}", "argument_brace"),
        )
    )

    _KNOWN_COMMANDS = frozenset(
        {
            "alpha",
            "beta",
            "gamma",
            "delta",
            "theta",
            "lambda",
            "sigma",
            "omega",
            "partial",
            "sum",
            "prod",
            "frac",
            "dfrac",
            "tfrac",
            "sqrt",
            "int",
            "iint",
            "iiint",
            "oint",
            "lim",
            "mathbb",
            "mathcal",
            "operatorname",
            "infty",
            "times",
            "cdot",
            "begin",
            "end",
            "placeholder",
        }
    )
    _COMMAND = re.compile(r"\\(?P<name>[A-Za-z]+)")
    _EXACT_TYPO_ALIASES = {
        "inty": "infty",
    }
    _EMPTY_FIRST_FRACTION = re.compile(
        r"(?P<command>\\(?:d?frac|tfrac))\s*\{\s*\}(?=\s*\{)"
    )
    _EMPTY_SECOND_FRACTION = re.compile(
        r"(?P<prefix>\\(?:d?frac|tfrac)\s*\{[^{}]*\}\s*)\{\s*\}"
    )
    _EMPTY_ROOT = re.compile(
        r"(?P<prefix>\\sqrt(?:\s*\[[^\]]*\])?\s*)\{\s*\}"
    )
    _EMPTY_SCRIPT = re.compile(r"(?P<operator>[_^])\s*\{\s*\}")
    _TRAILING_SCRIPT = re.compile(r"(?P<operator>[_^])\s*$")
    _TRAILING_BINARY = re.compile(r"(?P<operator>[=+\-*/])\s*$")

    def complete(self, partial: str) -> DeterministicCompletion | None:
        """Return a safe completion, or ``None`` when semantics are required."""
        source = partial.strip()
        if not source:
            return None

        for pattern, suffix, rule in self._TAIL_RULES:
            if pattern.search(source):
                return DeterministicCompletion(source + suffix, rule)

        repaired_commands = self._repair_command_typos(source)
        filled = self._fill_structural_holes(repaired_commands)
        if filled != source:
            rule = (
                "command_typo"
                if repaired_commands != source
                else "structural_placeholder"
            )
            return DeterministicCompletion(filled, rule)
        return None

    def _repair_command_typos(self, latex: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group("name")
            if name in self._KNOWN_COMMANDS:
                return match.group(0)
            if name in self._EXACT_TYPO_ALIASES:
                return "\\" + self._EXACT_TYPO_ALIASES[name]

            tail = latex[match.end():]
            if name == "si" and re.match(r"\s*_", tail):
                return r"\sum"

            distances = [
                (self._edit_distance(name, candidate), candidate)
                for candidate in self._KNOWN_COMMANDS
            ]
            best_distance = min(distance for distance, _ in distances)
            best = [
                candidate
                for distance, candidate in distances
                if distance == best_distance
            ]
            if best_distance != 1 or len(best) != 1:
                return match.group(0)
            return "\\" + best[0]

        return self._COMMAND.sub(replace, latex)

    def _fill_structural_holes(self, latex: str) -> str:
        placeholder = r"\placeholder{}"
        result = self._EMPTY_FIRST_FRACTION.sub(
            lambda match: f"{match.group('command')}{{{placeholder}}}",
            latex,
        )
        result = self._EMPTY_SECOND_FRACTION.sub(
            lambda match: f"{match.group('prefix')}{{{placeholder}}}",
            result,
        )
        result = self._EMPTY_ROOT.sub(
            lambda match: f"{match.group('prefix')}{{{placeholder}}}",
            result,
        )
        result = self._EMPTY_SCRIPT.sub(
            lambda match: f"{match.group('operator')}{{{placeholder}}}",
            result,
        )
        if self._TRAILING_SCRIPT.search(result):
            return self._TRAILING_SCRIPT.sub(
                lambda match: f"{match.group('operator')}{{{placeholder}}}",
                result,
            )
        if self._TRAILING_BINARY.search(result):
            return self._TRAILING_BINARY.sub(
                lambda match: f"{match.group('operator')}{placeholder}",
                result,
            )
        return result

    @staticmethod
    def _edit_distance(left: str, right: str) -> int:
        """Small Levenshtein implementation for the curated command vocabulary."""
        previous = list(range(len(right) + 1))
        for left_index, left_char in enumerate(left, start=1):
            current = [left_index]
            for right_index, right_char in enumerate(right, start=1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[right_index] + 1,
                        previous[right_index - 1]
                        + (left_char != right_char),
                    )
                )
            previous = current
        return previous[-1]
