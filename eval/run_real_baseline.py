"""Baseline runner for the golden set.

Modes:
- recorded: replay committed recordings through the pipeline (no model),
  evaluating the four assertion layers per entry. Proves the pipeline gate.
- live: run every entry against the real local model, measuring the
  structural pass rate and latency percentiles. Proves product usability.

Writes a report to eval/reports/<date>-baseline.md.

Usage:
  uv run --extra dev --extra eval python eval/run_real_baseline.py --mode recorded
  uv run --extra dev --extra eval python eval/run_real_baseline.py --mode live
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

from anchor_match import anchor_present
from golden_lib import (
    RecordedPlanner,
    anchor_variants,
    load_golden_set,
    load_recordings,
)

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.tools.registry import TeXToolset

DISCLAIMER = (
    "Development-regression scope; not a general benchmark. "
    "See eval/known-gaps.md for measured boundaries."
)


async def _run_entry(config, text, planner_factory):
    runtime = TeXadaAgentRuntime(
        config, model=planner_factory()
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    return await runtime.run(text)


def _evaluate(result, entry) -> dict:
    variants = anchor_variants(entry["anchor"])
    anchor_ok = (
        any(anchor_present(result.latex, v) for v in variants) if variants else None
    )
    return {
        "anchor": anchor_ok,
        "compile": result.valid,
        "render": bool(result.render.katex_html),
        "trace": bool(result.trace),
    }


async def _recorded(config) -> tuple[list[dict], list[dict]]:
    recordings = load_recordings()
    golden = {e["input"]: e for e in load_golden_set()}
    rows, skipped = [], []
    for text, rec in sorted(recordings.items()):
        entry = golden.get(text)
        if entry is None:
            skipped.append(text)
            continue
        result = await _run_entry(
            config, text, lambda rec=rec: RecordedPlanner(rec["turns"])
        )
        rows.append({"entry": entry, "result": result, "layers": _evaluate(result, entry)})
    return rows, skipped


async def _live(config) -> list[dict]:
    from texada.core.backend import BackendManager
    from texada.core.model import MiniCPMModel

    await BackendManager(config).ensure_ready()  # abort cleanly if unreachable

    rows = []
    for entry in load_golden_set():
        run_id = uuid.uuid4().hex
        try:
            result = await _run_entry(
                config, entry["input"], lambda: MiniCPMModel(config)
            )
        except Exception as exc:
            rows.append(
                {
                    "entry": entry,
                    "result": None,
                    "layers": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        rows.append(
            {
                "entry": entry,
                "result": result,
                "layers": _evaluate(result, entry),
                "run_id": run_id,
                "latency_ms": result.latency_ms,
            }
        )
    return rows


def _repair_rate(config) -> tuple[int, int]:
    import yaml

    path = Path(__file__).resolve().parent / "repair_dataset.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["entries"]
    toolset = TeXToolset(config)
    passed = 0
    for e in entries:
        try:
            repaired = toolset.repair_tex(e["broken"])["latex"]
            if toolset.compile_tex(repaired)["valid"]:
                toolset.render_math(repaired)
                passed += 1
        except Exception:
            continue
    return passed, len(entries)


def _layer_count(rows, layer):
    return sum(1 for r in rows if r["layers"] and r["layers"][layer])


def _write_report(path: Path, mode: str, model: str, rows, skipped, repair):
    passed, total = repair
    anchor_checked = [r for r in rows if r["layers"] and r["layers"]["anchor"] is not None]
    anchor_passed = [r for r in anchor_checked if r["layers"]["anchor"]]
    descriptive = [r for r in rows if r["layers"] and r["layers"]["anchor"] is None]
    lines = [
        f"# Baseline report — {date.today().isoformat()}",
        "",
        f"- Mode: **{mode}**",
        f"- Model: `{model}`",
        f"- Golden entries exercised: {len(rows)}"
        + (f" (skipped, no recording: {len(skipped)})" if skipped else ""),
        "",
        "## Golden set",
        "",
        f"- Structural pass rate (anchor layer): "
        f"{len(anchor_passed)}/{len(anchor_checked)}"
        + (f" ({100 * len(anchor_passed) / max(len(anchor_checked), 1):.1f}%)"
           if anchor_checked else ""),
        f"- Entries with descriptive (non-machine-checkable) anchors: {len(descriptive)}",
        f"- Compile layer: {_layer_count(rows, 'compile')}/{len(rows)}",
        f"- Render layer: {_layer_count(rows, 'render')}/{len(rows)}",
        f"- Trace layer: {_layer_count(rows, 'trace')}/{len(rows)}",
        "",
        "## Repair dataset (deterministic, brace-balance scope)",
        "",
        f"- Repair pass rate: {passed}/{total}"
        + (f" ({100 * passed / max(total, 1):.1f}%)" if total else ""),
        "",
        f"> {DISCLAIMER}",
        "",
    ]
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms")]
    if latencies:
        lines.insert(
            -3,
            f"- Latency p50 / p95: {statistics.median(latencies):.0f} ms / "
            f"{sorted(latencies)[max(int(len(latencies) * 0.95) - 1, 0)]:.0f} ms",
        )
    errors = [r for r in rows if r.get("error")]
    if errors:
        lines.append("## Errors")
        lines.append("")
        for r in errors:
            lines.append(f"- {r['entry']['id']}: {r['error']}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")
    print("\n".join(lines))


async def _main(args) -> int:
    config = TeXadaConfig()
    report = (
        args.report
        or Path(__file__).resolve().parent
        / "reports"
        / f"{date.today().isoformat()}-baseline-{args.mode}.md"
    )
    if args.mode == "recorded":
        rows, skipped = await _recorded(config)
        repair = _repair_rate(config)
    else:
        rows = await _live(config)
        skipped = []
        repair = _repair_rate(config)
    _write_report(report, args.mode, config.active_model_name, rows, skipped, repair)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["recorded", "live"], required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    try:
        return asyncio.run(_main(args))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
