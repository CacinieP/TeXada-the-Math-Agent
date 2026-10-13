"""Live single-checkpoint acceptance run; credentials come only from the environment.

Run from the repository after uv sync:
TEXADA_OPENAI_API_KEY=... uv run --no-sync python eval/run_minicpm_v47.py \
    --output-dir /path/to/evidence [--limit 12]

Golden-set anchors measure containment, not complete structural equivalence.
The local compile_tex tool is a syntax/AST check, not a whole-document TeX build.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anchor_match import anchor_present
from golden_lib import anchor_variants, load_golden_set
from openai import RateLimitError

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.model import MiniCPMModel
from texada.semantic.katex import shared_katex_parser

MODEL = "MiniCPM-V-4.7-1B"


async def run(args) -> None:
    key = os.environ.get("TEXADA_OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Export TEXADA_OPENAI_API_KEY before running live acceptance")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = TeXadaConfig(
        backend="openai_compatible",
        openai_base_url=os.environ.get("TEXADA_OPENAI_BASE_URL", "https://api.modelbest.cn/v1"),
        openai_api_key=key,
        openai_model_name=MODEL,
        openai_vision_model_name=MODEL,
        temperature=0.1,
        max_tokens=2048,
        agent_max_steps=3,
        nl_candidate_first=not args.planner_control,
        data_dir=output / "runtime-data",
    )
    config.ensure_dirs()
    await BackendManager(config).ensure_ready()
    model = MiniCPMModel(config)
    original_create = model._completion_create
    lock = threading.Lock()
    last_request = 0.0
    rate_limit_events = []

    def paced_create(**kwargs):
        nonlocal last_request
        with lock:
            for attempt in range(3):
                delay = args.request_interval - (time.monotonic() - last_request)
                if delay > 0:
                    time.sleep(delay)
                last_request = time.monotonic()
                try:
                    return original_create(**kwargs)
                except RateLimitError:
                    rate_limit_events.append({"attempt": attempt + 1, "retry_after_seconds": 30})
                    if attempt == 2:
                        raise
                    print("API RPM limit: waiting 30 seconds before bounded retry", flush=True)
                    time.sleep(30)

    model._completion_create = paced_create
    golden = load_golden_set()
    if args.limit:
        golden = golden[:args.limit]
    dataset = Path(__file__).with_name("golden_set.yaml")
    evidence = {
        "schema_version": 1,
        "time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model": MODEL,
        "vision_model": MODEL,
        "endpoint": config.active_base_url,
        "parameters": {"temperature": config.temperature, "max_tokens": config.max_tokens,
                       "agent_max_steps": config.agent_max_steps, "enable_thinking": False,
                       "nl_candidate_first": config.nl_candidate_first,
                       "request_interval_seconds": args.request_interval,
                       "rate_limit_max_attempts": 3},
        "golden_set_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "scope": "Live API integration; semantic anchor containment is not structural equivalence",
        "rows": [],
        "rate_limit_events": rate_limit_events,
    }
    try:
        for entry in golden:
            started = time.monotonic()
            row = {"id": entry["id"], "input": entry["input"], "anchor": entry["anchor"]}
            variants = anchor_variants(entry["anchor"])
            row["anchor_checked"] = bool(variants)
            runtime = TeXadaAgentRuntime(config, model=model)
            try:
                result = await runtime.run(entry["input"])
                row.update(
                    latex=result.latex, valid=result.valid,
                    rendered=bool(result.render.katex_html), committed=result.committed,
                    revision=result.revision, stop_reason=result.stop_reason,
                    tokens_used=result.tokens_used, trace=result.trace,
                    anchor_containment=any(anchor_present(result.latex, v) for v in variants)
                    if variants else None,
                )
            except Exception as exc:
                row.update(error=f"{type(exc).__name__}: {exc}".replace(key, "[REDACTED]"),
                           valid=False, rendered=False, committed=False,
                           anchor_containment=False if variants else None)
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            evidence["rows"].append(row)
            (output / "live-golden.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if len(evidence["rows"]) % 10 == 0 or len(evidence["rows"]) == len(golden):
                print(f"live golden: {len(evidence['rows'])}/{len(golden)}", flush=True)
    finally:
        if model._client is not None:
            model._client.close()
        shared_katex_parser().close()
    rows = evidence["rows"]
    checked = [row for row in rows if row["anchor_checked"]]
    times = sorted(row["elapsed_seconds"] for row in rows)
    summary = {
        "total": len(rows), "errors": sum("error" in row for row in rows),
        "anchor_containment_passed": sum(bool(row["anchor_containment"]) for row in checked),
        "anchor_checked": len(checked), "anchor_not_checked": len(rows) - len(checked),
        "syntax_valid": sum(row["valid"] for row in rows),
        "rendered": sum(row["rendered"] for row in rows),
        "committed": sum(row["committed"] for row in rows),
        "latency_p50_seconds": round(statistics.median(times), 3),
        "latency_p95_seconds": times[max(0, int(len(times) * 0.95) - 1)],
    }
    evidence["summary"] = summary
    (output / "live-golden.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--request-interval", type=float, default=3.2)
    parser.add_argument("--planner-control", action="store_true",
                        help="Use the original full-schema NL Planner initialization")
    arguments = parser.parse_args()
    if arguments.limit < 0:
        parser.error("--limit must be nonnegative")
    if arguments.request_interval < 0:
        parser.error("--request-interval must be nonnegative")
    asyncio.run(run(arguments))
