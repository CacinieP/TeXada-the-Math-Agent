"""Deterministic repair dataset: every entry is genuinely broken and must
become valid and renderable after the deterministic repair_tex tool.

Scope: brace-balance breakage only (the documented boundary of the current
deterministic repairer — see eval/known-gaps.md for measured non-goals).
No model is involved, so this suite runs in regular CI.
"""
from pathlib import Path

import pytest
import yaml

from texada.config import TeXadaConfig
from texada.tools.registry import TeXToolset

REPO = Path(__file__).resolve().parents[1]
DATA = yaml.safe_load(
    (REPO / "eval" / "repair_dataset.yaml").read_text(encoding="utf-8")
)["entries"]


def test_dataset_has_expected_size():
    assert len(DATA) == 53


def test_dataset_entries_are_genuinely_broken():
    toolset = TeXToolset(TeXadaConfig(data_dir=REPO / ".tmp-test"))
    for e in DATA:
        assert not toolset.compile_tex(e["broken"])["valid"], (
            f"{e['id']}: broken input unexpectedly valid: {e['broken']!r}"
        )


@pytest.mark.parametrize("entry", DATA, ids=lambda e: e["id"])
async def test_repair_makes_entry_valid_and_renderable(tmp_path, entry):
    toolset = TeXToolset(TeXadaConfig(data_dir=tmp_path))
    repaired = toolset.repair_tex(entry["broken"])["latex"]
    assert toolset.compile_tex(repaired)["valid"], (
        f"{entry['id']}: not valid after repair: {repaired!r}"
    )
    toolset.render_math(repaired)  # raises ValueError when invalid
