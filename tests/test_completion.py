"""Deterministic completion regression tests from the v0.3.1 UI audit."""

import pytest

from texada.core.completion import DeterministicCompletionEngine


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        ("a_", r"a_{\placeholder{}}"),
        ("x^", r"x^{\placeholder{}}"),
        (r"x_i^{", r"x_i^{\placeholder{}}"),
        (r"y^n_{", r"y^n_{\placeholder{}}"),
        (r"\lim_", r"\lim_{\placeholder{}}"),
        (r"\int_0^", r"\int_0^{\placeholder{}}"),
        (r"\frac{}{b}", r"\frac{\placeholder{}}{b}"),
        (r"\frac{a}{}", r"\frac{a}{\placeholder{}}"),
        (r"\sqrt{}", r"\sqrt{\placeholder{}}"),
        (
            r"\sum_{}^{n} x_i",
            r"\sum_{\placeholder{}}^{n} x_i",
        ),
        (
            r"\sum_{i=1}^{} x_i",
            r"\sum_{i=1}^{\placeholder{}} x_i",
        ),
        ("f(x)=", r"f(x)=\placeholder{}"),
        ("x+", r"x+\placeholder{}"),
    ],
)
def test_structural_holes_use_placeholders_without_guessing(partial, expected):
    completion = DeterministicCompletionEngine().complete(partial)

    assert completion is not None
    assert completion.latex == expected


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        (r"x+\alxha", r"x+\alpha"),
        (r"x+\betta", r"x+\beta"),
        (r"x+\gaxma", r"x+\gamma"),
        (r"\frax{a}{b}", r"\frac{a}{b}"),
        (r"\sqr{x}", r"\sqrt{x}"),
        (
            r"\operatxrname{rank}(A)",
            r"\operatorname{rank}(A)",
        ),
        (r"\mathbx{R}", r"\mathbb{R}"),
        (
            r"\si_{n=0}^{\inty}",
            r"\sum_{n=0}^{\infty}",
        ),
        (r"a\tixes b", r"a\times b"),
    ],
)
def test_unique_common_command_typos_are_fixed_locally(partial, expected):
    completion = DeterministicCompletionEngine().complete(partial)

    assert completion is not None
    assert completion.rule == "command_typo"
    assert completion.latex == expected


def test_unknown_commands_are_not_guessed_when_no_unique_neighbour_exists():
    assert DeterministicCompletionEngine().complete(r"\futuremath{x}") is None
