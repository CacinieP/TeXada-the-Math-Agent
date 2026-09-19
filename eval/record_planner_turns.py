"""Capture real planner turns for every golden set entry.

Requires a reachable local model backend (Ollama or compatible). Writes one
JSON recording per entry into eval/recordings/ for use by the recorded-mode
CI gate.

Usage: uv run --extra dev --extra eval python eval/record_planner_turns.py [--out DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path

from golden_lib import GOLDEN_SET, load_golden_set

from texada.agent.protocol import PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel


class RecordingPlanner:
    """Wraps a real planner and records every turn it produces."""

    def __init__(self, inner):
        self._inner = inner
        self.turns: list[dict] = []

    async def plan(self, messages, tools):
        turn: PlannerTurn = await self._inner.plan(messages, tools)
        self.turns.append(
            {
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in turn.tool_calls
                ],
            }
        )
        return turn

    async def generate_latex(self, user_input, intent, *, force_operators=None):
        return await self._inner.generate_latex(
            user_input, intent, force_operators=force_operators
        )

    @staticmethod
    def extract_latex(content: str) -> str:
        return content.strip()


def _slug(entry_id: str, text: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]+", "-", text).strip("-")[:40]
    return f"{entry_id}-{safe}" if safe else entry_id


async def _record(config: TeXadaConfig, out_dir: Path) -> int:
    import json

    entries = load_golden_set()
    failures = 0
    for entry in entries:
        recorder = RecordingPlanner(MiniCPMModel(config))
        runtime = TeXadaAgentRuntime(config, model=recorder)
        run_id = uuid.uuid4().hex
        try:
            result = await runtime.run(entry["input"])
        except Exception as exc:  # backend unreachable, timeout, protocol drift
            failures += 1
            print(f"  {entry['id']}: FAILED {type(exc).__name__}: {exc}")
            continue
        payload = {
            "run_id": run_id,
            "input": entry["input"],
            "anchor": entry["anchor"],
            "turns": recorder.turns,
            "final_latex": result.latex,
            "valid": result.valid,
            "latency_ms": round(result.latency_ms, 1),
            "stop_reason": result.stop_reason,
        }
        path = out_dir / f"{_slug(entry['id'], entry['input'])}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  {entry['id']}: ok ({len(recorder.turns)} turns, {result.stop_reason})")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).resolve().parent / "recordings"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    config = TeXadaConfig()
    print(f"Recording {GOLDEN_SET} entries with model {config.active_model_name!r}")
    try:
        failures = asyncio.run(_record(config, args.out))
    except Exception as exc:
        print(f"error: recording aborted: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"{failures} entries failed", file=sys.stderr)
        return 1
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
