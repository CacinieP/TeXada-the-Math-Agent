"""Detect "answered instead of transcribed" output.

The prompts already forbid evaluation (``core/prompts.py`` rule 9 and the agent
system prompt), but a 1B model still turns ``2+3`` into ``2+3=5`` or sums
``\\sum_{k=1}^{100}k`` into ``5050``. TeXada's contract is to typeset what the
user described, not to compute it.

This module is a cheap structural check, not a math oracle: an equality whose
right-hand side is a bare numeric constant that the user never wrote means the
model computed something. It never rewrites the formula — the router uses it to
request one constrained retry and to flag the run for review.
"""

from __future__ import annotations

import re

_NUMBER = r"-?\d+(?:\.\d+)?"
_EQUALS_NUMBER = re.compile(rf"=\s*({_NUMBER})")
_EQUALS_CONSTANT = re.compile(r"=\s*(e|\\pi)(?![A-Za-z])")
_NUMERAL = re.compile(_NUMBER)
_ARITHMETIC_ONLY = re.compile(r"^[\s\d+\-*/^().×÷=<>]+$")


def _numerals(text: str) -> set[str]:
    """Numbers as written, normalized for ``+5``/``5`` and ``5.0``/``5``."""
    found: set[str] = set()
    for match in _NUMERAL.finditer(text or ""):
        value = match.group(0).lstrip("+")
        if value.endswith(".0"):
            value = value[:-2]
        found.add(value)
    return found


def is_arithmetic_input(text: str) -> bool:
    """True for input that is nothing but numbers and operators."""
    stripped = (text or "").strip()
    return (
        bool(stripped)
        and bool(re.search(r"\d", stripped))
        and bool(_ARITHMETIC_ONLY.match(stripped))
    )


def suspects_evaluation(user_input: str, latex: str) -> bool:
    """Whether ``latex`` looks like it evaluated ``user_input`` instead of transcribing it."""
    if not latex or "=" not in latex:
        return False

    known = _numerals(user_input)
    for numeral in _EQUALS_NUMBER.findall(latex):
        value = numeral.lstrip("+")
        if value.endswith(".0"):
            value = value[:-2]
        if value not in known:
            return True

    # `\lim_{x\to 0}(1+x)^{1/x} = e`: the constant is the computed limit, and
    # the user never wrote that constant.
    for constant in _EQUALS_CONSTANT.findall(latex):
        token = "e" if constant == "e" else "\\pi"
        if token == "e" and not re.search(r"(?<![A-Za-z\\])e(?![A-Za-z])", user_input):
            return True
        if token == "\\pi" and "π" not in user_input and "pi" not in user_input.lower():
            return True

    return False
