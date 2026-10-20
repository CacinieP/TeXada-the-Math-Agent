"""Deterministic completion regression tests from the v0.3.1 UI audit."""

import pytest

from texada.core.completion import (
    DeterministicCompletionEngine,
    suggest_inline,
)


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


@pytest.mark.parametrize(
    ("before", "after", "expected_text", "expected_rule"),
    [
        (r"\frac{a}{", "}", r"\placeholder{}", "empty_group"),
        (r"\frac{}{", "}", r"\placeholder{}", "empty_group"),
        (r"x^{", "}", r"\placeholder{}", "empty_group"),
        (r"a_{", "}", r"\placeholder{}", "empty_group"),
        (r"\sqrt{", "}", r"\placeholder{}", "empty_group"),
        (r"\frac{甲}{", "}", r"\placeholder{}", "empty_group"),
    ],
)
def test_empty_group_at_cursor_only_suggests_placeholder(
    before, after, expected_text, expected_rule
):
    suggestion = suggest_inline(before, after)

    assert suggestion is not None
    assert suggestion.text == expected_text
    assert suggestion.rule == expected_rule
    assert before + suggestion.text + after == before + expected_text + after


def test_inline_suggestion_is_insert_only_and_preserves_both_sides():
    before = r"y = \frac{\sin(x)}{"
    after = r"} + 1"

    suggestion = suggest_inline(before, after)

    assert suggestion is not None
    assert before + suggestion.text + after == (
        r"y = \frac{\sin(x)}{\placeholder{}} + 1"
    )


def test_filled_group_or_existing_right_side_is_not_rewritten():
    assert suggest_inline(r"x^", "{2}") is None
    assert suggest_inline(r"\frac{a}{b", "}") is None
    assert suggest_inline(r"\sqrt{", "x}") is None
    assert suggest_inline(r"\frac{a}", "{b}") is None


@pytest.mark.parametrize(
    ("before", "expected_text", "expected_rule"),
    [
        ("x^", r"{\placeholder{}}", "script_brace"),
        (r"y^n_", r"{\placeholder{}}", "script_brace"),
        ("f(x)=", r"\placeholder{}", "binary_operand"),
        ("x+", r"\placeholder{}", "binary_operand"),
        (r"\int", r"_{0}^{1} f(x)\,dx", "integral_prefix"),
        (r"\alp", "ha", "command_prefix"),
        (r"\frac{", r"\placeholder{}}{\placeholder{}}", "fraction_prefix"),
    ],
)
def test_open_ended_cursor_reuses_structural_and_prefix_rules(
    before, expected_text, expected_rule
):
    suggestion = suggest_inline(before, "")

    assert suggestion is not None
    assert suggestion.text == expected_text
    assert suggestion.rule == expected_rule


def test_escaped_literal_brace_gets_no_placeholder():
    assert suggest_inline(r"x\{", "}") is None


def test_empty_or_whitespace_context_has_no_suggestion():
    assert suggest_inline("", "") is None
    assert suggest_inline("   ", "") is None
    assert suggest_inline(r"x + 1", "") is None


def test_open_ended_group_gets_a_closed_placeholder():
    suggestion = suggest_inline(r"\frac{a}{", "")

    assert suggestion is not None
    assert suggestion.rule == "empty_group_open"
    assert r"\frac{a}{" + suggestion.text == r"\frac{a}{\placeholder{}}"


def test_inline_suggestions_are_deterministic_and_model_free():
    first = suggest_inline(r"\frac{a}{", "}")
    second = suggest_inline(r"\frac{a}{", "}")

    assert first == second
