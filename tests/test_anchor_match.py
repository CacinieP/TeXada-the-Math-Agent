"""Anchor matcher unit tests: equivalent spellings pass, structural loss is
detected, subsequence semantics hold."""
from anchor_match import anchor_present, flatten_tokens


def test_equivalent_spellings_pass():
    assert anchor_present(r"\dfrac{a}{b}", r"\frac{a}{b}") is True
    assert anchor_present(r"\lvert x\rvert\le 1", r"|x|\le 1") is True
    assert anchor_present(r"P(A\mid B)", r"P(A|B)") is True
    assert anchor_present(r"x\cdot y+z", r"xy+z") is True


def test_delimiter_under_script_is_a_known_mvp_limitation():
    # Known limitation (recorded in eval/known-gaps.md): the KaTeX AST attaches
    # the script to different nodes in \left(x+1\right)^2 vs (x+1)^2, so the
    # token subsequence cannot unify them. Upgrade path: structural containment
    # matching. Do not weaken the matcher to force this green.
    assert anchor_present(r"\left(x+1\right)^2", r"(x+1)^2") is False


def test_dropped_or_changed_operator_detected():
    assert anchor_present(r"x+y", r"x\cdot y") is False
    assert anchor_present(r"x\cdot y", r"x+y") is False


def test_degradation_detected():
    # iiint downgraded to int must fail an iiint anchor
    assert anchor_present(r"\int_{0}^{1} f\,dx", r"\iiint_{0}^{1} f\,dx") is False
    assert anchor_present(r"\iiint_{0}^{1} f\,dx", r"\int_{0}^{1} f\,dx") is False


def test_subsequence_semantics():
    tokens = flatten_tokens(r"\frac{a}{b}+c")
    assert "fraction:frac" in tokens
    # implicit multiplication tolerated by subsequence matching
    assert anchor_present(r"x\cdot y+z", r"xy+z") is True


def test_empty_or_unparseable_anchor_is_not_a_false_pass():
    assert anchor_present(r"x+1", r"") is False
