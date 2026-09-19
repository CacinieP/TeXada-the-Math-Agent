"""One-shot generator: parse the 100 manual test prompts in
docs/test-prompts-100.md into a committed golden set fixture.

Usage: uv run python eval/generate_golden_set.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "docs" / "test-prompts-100.md"
TARGET = REPO / "eval" / "golden_set.yaml"

HEADING = re.compile(r"^## ([A-H])\.\s*(.+)$")
ROW = re.compile(r"^\|\s*(\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def _clean(cell: str) -> str:
    return cell.replace("`", "").strip()


def parse_prompts(md_path: Path) -> list[dict]:
    entries: list[dict] = []
    category = ""
    for line in md_path.read_text(encoding="utf-8").splitlines():
        heading = HEADING.match(line)
        if heading:
            letter, _title = heading.groups()
            category = letter
            continue
        row = ROW.match(line)
        if row and category:
            entry_id, input_text, anchor = row.groups()
            entries.append(
                {
                    "id": entry_id,
                    "category": category,
                    "input": input_text.strip(),
                    "anchor": _clean(anchor),
                }
            )
    return entries


def main() -> int:
    entries = parse_prompts(SOURCE)
    ids = [e["id"] for e in entries]
    if len(entries) != 100:
        print(f"error: expected 100 entries, parsed {len(entries)}", file=sys.stderr)
        return 1
    if len(set(ids)) != len(ids):
        print("error: duplicate ids", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            {"entries": entries}, fh, allow_unicode=True, sort_keys=False
        )
    print(f"wrote {TARGET.relative_to(REPO)}: {len(entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
