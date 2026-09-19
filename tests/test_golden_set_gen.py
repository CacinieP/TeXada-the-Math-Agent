"""Generator tests: the committed golden set fixture must faithfully mirror
the 100 manual test prompts in docs/test-prompts-100.md."""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _load():
    data = yaml.safe_load(
        (REPO / "eval" / "golden_set.yaml").read_text(encoding="utf-8")
    )
    return data["entries"]


def test_generated_fixture_has_100_unique_entries():
    entries = _load()
    assert len(entries) == 100
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == 100


def test_every_entry_has_input_and_anchor():
    for e in _load():
        assert e["input"].strip()
        assert e["anchor"].strip()


def test_all_eight_categories_present():
    entries = _load()
    assert len({e["category"] for e in entries}) == 8
    letters = sorted({e["category"] for e in entries})
    assert letters == sorted("ABCDEFGH")
