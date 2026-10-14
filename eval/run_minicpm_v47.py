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
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from anchor_match import anchor_present
from golden_lib import anchor_variants, load_golden_set
from openai import RateLimitError
from structural_match import (
    NORMALIZATION_VERSION,
    check_references,
    load_references,
    summarize_structure,
)

from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.inference_fingerprint import (
    build_inference_identity,
    canonical_sha256,
    collect_inference,
    sanitized_endpoint,
    unavailable_inference_fingerprint,
    without_inference_collection,
)
from texada.core.model import MiniCPMModel
from texada.semantic.katex import shared_katex_parser

MODEL = "MiniCPM-V-4.7-1B"


async def run(args) -> None:
    reference_path = getattr(args, "structure_references", None)
    reference_bytes = reference_path.read_bytes() if reference_path else None
    references = load_references(reference_path, text=reference_bytes.decode("utf-8")
                                 if reference_bytes is not None else None)
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
        failure_context_projection=not getattr(args, "raw_failure_context", False),
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
    selected_dataset = getattr(args, "dataset", None)
    dataset = selected_dataset or Path(__file__).with_name("golden_set.yaml")
    dataset_bytes = dataset.read_bytes()
    dataset_version = "texada-golden-set-v1"
    if selected_dataset is None:
        golden = load_golden_set()
    else:
        data = yaml.safe_load(dataset_bytes)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise ValueError("dataset must contain an entries list")
        golden = data["entries"]
        dataset_version = data.get("version", "explicit-golden-set")
        if not isinstance(dataset_version, str) or not dataset_version:
            raise ValueError("dataset version must be a nonempty string")
        ids = set()
        for row in golden:
            if (not isinstance(row, dict)
                    or any(not isinstance(row.get(key), str) or not row[key].strip()
                           for key in ("id", "input", "anchor"))
                    or row["id"] in ids):
                raise ValueError("dataset rows require unique ids, inputs and anchors")
            ids.add(row["id"])
    if dataset.read_bytes() != dataset_bytes:
        raise RuntimeError("Golden dataset changed while loading; rerun with a stable fixture")
    if args.limit:
        golden = golden[:args.limit]
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    identity = build_inference_identity(
        config, dataset_version=dataset_version, dataset_sha256=dataset_sha256,
    )
    evidence = {
        "schema_version": 1,
        "time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model": MODEL,
        "vision_model": MODEL,
        "endpoint": sanitized_endpoint(config.active_base_url),
        "inference_identity": identity,
        "inference_identity_sha256": canonical_sha256(identity),
        "parameters": {"temperature": config.temperature, "max_tokens": config.max_tokens,
                       "agent_max_steps": config.agent_max_steps, "enable_thinking": False,
                       "nl_candidate_first": config.nl_candidate_first,
                       "failure_context_projection": config.failure_context_projection,
                       "request_interval_seconds": args.request_interval,
                       "rate_limit_max_attempts": 3},
        "golden_set_sha256": dataset_sha256,
        "scope": "Live API integration; semantic anchor containment is not structural equivalence",
        "strict_structure_evaluation": {
            "normalization_version": NORMALIZATION_VERSION,
            "references_sha256": hashlib.sha256(reference_bytes).hexdigest()
            if reference_bytes is not None else None,
            "reference_case_count": len(references),
            "reference_origin": "explicit_full_expression_registry" if reference_path else None,
        },
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
            collector = None
            fingerprint_fallback = None
            try:
                with ExitStack() as collection:
                    try:
                        collector = collection.enter_context(collect_inference(identity))
                    except Exception as exc:
                        fingerprint_fallback = unavailable_inference_fingerprint(exc)
                        collection.enter_context(without_inference_collection())
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
            row["inference_fingerprint"] = (
                collector.snapshot() if collector is not None else fingerprint_fallback
            )
            # Keep the legacy runtime/containment latency boundary unchanged.
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            strict_started = time.monotonic()
            row["strict_structure"] = check_references(
                row.get("latex"), references.get(entry["id"], [])
            ).to_dict()
            row["strict_structure_elapsed_seconds"] = round(time.monotonic() - strict_started, 6)
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
        "strict_structure": summarize_structure(rows),
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
    parser.add_argument("--dataset", type=Path,
                        help="Explicit versioned input dataset; default keeps original golden set")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--request-interval", type=float, default=3.2)
    parser.add_argument("--planner-control", action="store_true",
                        help="Use the original full-schema NL Planner initialization")
    parser.add_argument("--raw-failure-context", action="store_true",
                        help="Paired control: retain failed tool exchanges in Planner history")
    parser.add_argument("--structure-references", type=Path,
                        help="Opt in with an authored full-expression reference registry")
    arguments = parser.parse_args()
    if arguments.limit < 0:
        parser.error("--limit must be nonnegative")
    if arguments.request_interval < 0:
        parser.error("--request-interval must be nonnegative")
    asyncio.run(run(arguments))
