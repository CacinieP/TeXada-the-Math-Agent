"""Actual local candidate-generation run, with no deterministic formula replacement."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.inference_fingerprint import build_inference_identity, collect_inference
from texada.core.intent import IntentClassifier
from texada.core.model import MiniCPMModel
from texada.core.operator_guard import OperatorDriftGuard
from texada.core.symbols import SymbolEngine
from texada.semantic.katex import shared_katex_parser


def visible_formula(content: str | None) -> str:
    """Evaluation fallback preserves a visible final answer rejected by host heuristics."""
    if not content:
        return ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I).strip()
    if re.search(r"<think\b", content, flags=re.I):
        return ""
    fence = re.fullmatch(r"```(?:latex|tex|math)?\s*\n?(.*?)\n?```", content, re.S)
    if fence:
        content = fence[1].strip()
    for start, end in (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$")):
        if content.startswith(start) and content.endswith(end):
            return content[len(start):-len(end)].strip()
    return content


async def run(args) -> None:
    blob = args.dataset.read_bytes()
    data = yaml.safe_load(blob)
    references_blob = args.references.read_bytes()
    reference_digest = hashlib.sha256(references_blob).hexdigest()
    rows = data["entries"]
    config = TeXadaConfig(
        backend="openai_compatible", openai_base_url="http://127.0.0.1:18347/v1",
        openai_api_key="local-no-key", openai_model_name="MiniCPM-V-4.7-1B",
        openai_vision_model_name="MiniCPM-V-4.7-1B", temperature=0.1, max_tokens=2048,
        nl_candidate_first=True, data_dir=args.output_dir/"runtime-data",
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    await BackendManager(config).ensure_ready()
    model = MiniCPMModel(config)
    original = model._completion_create
    captured = []

    def capture(**kwargs):
        response = original(**kwargs)
        if response.choices:
            captured.append(response.choices[0].message.content)
        return response

    model._completion_create = capture
    symbols, classifier, guard = SymbolEngine(), IntentClassifier(), OperatorDriftGuard()
    identity = build_inference_identity(
        config, dataset_version=data.get("version", "texada-golden-set-v1"),
        dataset_sha256=hashlib.sha256(blob).hexdigest(), tool_schemas=[],
    )
    evidence = {
        "schema_version": 1, "phase": "model_candidate_generation",
        "scope": "Production candidate prompts, pretranslation and model retries; no deterministic "
        "candidate engine, planner tool loop, syntax repair or commit. "
        "References never sent to model.",
        "time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "dataset_sha256": hashlib.sha256(blob).hexdigest(),
        "references_sha256": reference_digest, "server_seed": 47,
        "inference_identity": identity, "rows": [],
    }
    try:
        for entry in rows:
            captured.clear()
            start = time.monotonic()
            prompt = entry["input"]
            preprocessed = symbols.pre_translate(prompt)
            row = {"id": str(entry["id"]).zfill(3), "input": prompt,
                   "preprocessed_input": preprocessed}
            with collect_inference(identity) as collector:
                try:
                    row["latex"] = await model.generate_latex(
                        preprocessed, classifier.classify(prompt).intent,
                        force_operators=guard.forced_operators(preprocessed, prompt),
                        deadline_monotonic=start+config.api_request_timeout_seconds,
                    )
                    row["extraction"] = "production_wrapper"
                except Exception as exc:
                    row["production_error"] = type(exc).__name__+": "+str(exc)
                    row["latex"] = visible_formula(captured[-1] if captured else None)
                    row["extraction"] = "visible_final_response_for_evaluation_only"
            row["raw_final_contents"] = list(captured)
            row["inference_fingerprint"] = collector.snapshot()
            row["tokens_used"] = model.consume_tokens_used()
            parsed = shared_katex_parser().parse(row["latex"])
            row["katex_syntax_valid"] = parsed.ok
            row["elapsed_seconds"] = round(time.monotonic()-start, 3)
            evidence["rows"].append(row)
            (args.output_dir/"live-candidates.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2),
            )
            if len(evidence["rows"]) % 10 == 0:
                print(f"model candidates: {len(evidence['rows'])}/{len(rows)}", flush=True)
        if args.dataset.read_bytes() != blob or args.references.read_bytes() != references_blob:
            raise RuntimeError("dataset or references changed during the run")
    finally:
        if model._client is not None:
            model._client.close()
        shared_katex_parser().close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
