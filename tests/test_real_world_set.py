"""Structural tests for the real-world NL → LaTeX corpus.

The corpus (``eval/real_world_set.yaml``) is the complement of the 100-entry
golden set: it covers named theorems, lecture/exam sentences, the
"never answer, only transcribe" boundary, and half-finished LaTeX. These tests
are offline — they validate the fixture and the judging rules, not the model.
"""

import re
from pathlib import Path

import pytest
from anchor_match import anchor_present
from golden_lib import anchor_variants
from real_world_lib import (
    CATEGORIES,
    forbidden_hits,
    judge,
    load_real_world_set,
    parse_ok,
    prose_leak,
    strip_delimiters,
    text_only,
)

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs" / "test-prompts-real-world.md"

ENTRIES = load_real_world_set()
BY_CATEGORY = {c: [e for e in ENTRIES if e["category"] == c] for c in CATEGORIES}
CJK = re.compile(r"[\u4e00-\u9fff]")


def test_entry_ids_are_unique():
    ids = [e["id"] for e in ENTRIES]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


def test_categories_are_the_declared_five():
    assert set(BY_CATEGORY) == set(CATEGORIES)
    for category, entries in BY_CATEGORY.items():
        assert entries, f"category {category} has no entries"


def test_every_entry_is_traceable():
    for e in ENTRIES:
        assert e["input"].strip()
        assert e["anchor"].strip()
        assert e["reference"].strip()
        assert e["source"].strip(), f"{e['id']} lacks a source"


def test_anchor_variants_are_machine_checkable():
    for e in ENTRIES:
        variants = anchor_variants(e["anchor"])
        assert variants, f"{e['id']} anchor yields no LaTeX variant"
        for variant in variants:
            assert not CJK.search(variant), f"{e['id']} anchor variant has CJK"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["id"])
def test_reference_parses_as_katex(entry):
    ok, detail = parse_ok(entry["reference"])
    assert ok, f"{entry['id']} reference is not valid KaTeX: {detail}"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["id"])
def test_anchor_is_satisfied_by_its_own_reference(entry):
    reference = entry["reference"]
    variants = anchor_variants(entry["anchor"])
    assert any(anchor_present(reference, v) for v in variants), (
        f"{entry['id']}: anchor {entry['anchor']!r} not contained in "
        f"its own reference {reference!r}"
    )


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["id"])
def test_forbid_list_never_matches_its_own_reference(entry):
    # A forbid fragment that also occurs in the reference would make the entry
    # unsatisfiable.
    assert forbidden_hits(entry["reference"], entry.get("forbid")) == []


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["id"])
def test_judge_accepts_the_reference(entry):
    ok, reasons = judge(entry, entry["reference"])
    assert ok, f"{entry['id']} rejected its own reference: {reasons}"


def _entry(entry_id):
    return next(e for e in ENTRIES if e["id"] == entry_id)


def test_text_only_output_is_rejected():
    entry = _entry("rw-011")  # 泰勒公式
    ok, reasons = judge(entry, "\\text{泰勒公式}")
    assert not ok and any("text-only" in r for r in reasons)


def test_plain_chinese_answer_is_rejected():
    entry = _entry("rw-032")  # D(X-Y)
    ok, reasons = judge(entry, "当 X 与 Y 独立时，D(X-Y) = D(X) + D(Y)")
    assert not ok and any("CJK prose" in r for r in reasons)


def test_evaluated_arithmetic_is_rejected():
    entry = _entry("rw-036")  # 2+3 等于几
    ok, reasons = judge(entry, "2+3=5")
    assert not ok and any("forbidden" in r for r in reasons)


def test_summed_value_is_rejected():
    entry = _entry("rw-038")  # 1 加到 100
    ok, reasons = judge(entry, r"\sum_{k=1}^{100}k=5050")
    assert not ok and any("forbidden" in r for r in reasons)


def test_typo_command_is_rejected_as_unparseable():
    entry = _entry("rw-052")  # \bet → \beta
    ok, reasons = judge(entry, r"\alpha+\bet")
    assert not ok


def test_operator_degradation_is_rejected():
    entry = _entry("rw-001")  # 格林公式 needs \oint
    ok, reasons = judge(
        entry,
        r"\iint_D\left(\frac{\partial Q}{\partial x}-\frac{\partial P}{\partial y}\right)dx\,dy",
    )
    assert not ok and any("anchor missing" in r for r in reasons)


def test_dollar_wrapped_output_is_accepted():
    entry = _entry("rw-049")  # \int_0^1
    ok, reasons = judge(entry, r"$$\int_0^1 f(x)\,dx$$")
    assert ok, reasons
    assert strip_delimiters(r"$$\int_0^1$$") == r"\int_0^1"


def test_prose_leak_allows_label_groups():
    assert not prose_leak(r"\int_0^{\frac{\pi}{2}}\sin^n x\,dx\ \text{ 偶}")
    assert prose_leak(r"答案是 \int_0^1 f\,dx")


def test_text_only_allows_plain_formula():
    assert not text_only("2+3")
    assert text_only("夹逼定理")


def test_docs_table_matches_the_fixture():
    rows = re.findall(r"^\|\s*(rw-\d{3})\s*\|", DOCS.read_text(encoding="utf-8"), re.M)
    assert rows == [e["id"] for e in ENTRIES], (
        "docs/test-prompts-real-world.md is out of sync with "
        "eval/real_world_set.yaml (regenerate the table)"
    )
