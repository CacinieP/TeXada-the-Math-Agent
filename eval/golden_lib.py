"""Shared helpers for golden set tests and baseline runs.

Loads the committed fixture and recordings, replays recorded planner turns,
and splits multi-variant anchors into machine-checkable LaTeX variants.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from texada.agent.protocol import PlannerToolCall, PlannerTurn

REPO = Path(__file__).resolve().parents[1]
GOLDEN_SET = REPO / "eval" / "golden_set.yaml"
RECORDINGS_DIR = REPO / "eval" / "recordings"

_CJK = re.compile(r"[\u4e00-\u9fff]")
_SPLIT = re.compile(r"\s*或\s*|\s*、\s*")


def load_golden_set() -> list[dict]:
    data = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    return data["entries"]


def load_recordings() -> dict[str, dict]:
    recordings: dict[str, dict] = {}
    if not RECORDINGS_DIR.is_dir():
        return recordings
    for path in sorted(RECORDINGS_DIR.glob("*.json")):
        rec = yaml.safe_load(path.read_text(encoding="utf-8"))
        recordings[rec["input"]] = rec
    return recordings


def anchor_variants(anchor: str) -> list[str]:
    """Split a prompt anchor into machine-checkable LaTeX variants.

    Alternatives joined by 或 / 、 are split apart. Descriptive fragments
    (containing CJK text, e.g. 或等价结构) are dropped; an entry whose anchor
    is purely descriptive yields an empty list and its anchor layer is
    skipped (triaged in eval/known-gaps.md).
    """
    variants = []
    for part in _SPLIT.split(anchor):
        part = part.strip()
        if not part or _CJK.search(part):
            continue
        variants.append(part)
    return variants


class RecordedPlanner:
    """Replays a recorded planner turn sequence in order.

    Each ``plan()`` call consumes one recorded turn. A turn with no tool
    calls terminates the loop; its ``content`` carries the final LaTeX.
    """

    def __init__(self, turns: list[dict]):
        self._turns = [dict(t) for t in turns]
        self._final_latex = ""

    async def plan(self, messages, tools):
        if not self._turns:
            raise RuntimeError("recording exhausted: unexpected extra plan() call")
        turn = self._turns.pop(0)
        calls = [
            PlannerToolCall(
                id=call.get("id", f"call_{index}"),
                name=call["name"],
                arguments=call.get("arguments", {}),
            )
            for index, call in enumerate(turn.get("tool_calls", []))
        ]
        if not calls:
            self._final_latex = turn.get("content", "").strip()
        return PlannerTurn(
            content=turn.get("content", ""),
            tool_calls=calls,
            tokens_used=turn.get("tokens_used", 0),
        )

    async def generate_latex(self, user_input, intent, *, force_operators=None):
        return self._final_latex

    @staticmethod
    def extract_latex(content: str) -> str:
        return content.strip()
