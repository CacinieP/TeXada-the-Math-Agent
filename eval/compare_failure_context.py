"""Paired public failure-trajectory replay, with real tools and a scripted planner.

This measures protocol retention, recovery under fixed proposals, and local
runtime latency. It is not a model-quality or API-speed benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock

from structural_match import compare_structure

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.inference_fingerprint import build_inference_identity, collect_inference


async def compare():
    cases = [
        ("unknown-small", [PlannerTurn(tool_calls=[PlannerToolCall(
            "bad", "unsupported_action", {"unknown_parameter": "private failed parameters"},
        )]), PlannerTurn(content="x+1")], "x+1"),
        ("unknown-large", [PlannerTurn(tool_calls=[PlannerToolCall(
            "bad", "unsupported_action", {"unknown_parameter": "synthetic-invalid " * 150},
        )]), PlannerTurn(content="x+1")], "x+1"),
        ("syntax-repair", [PlannerTurn(tool_calls=[PlannerToolCall(
            "bad", "compile_tex", {"latex": r"\frac{x}{2"},
        )]), PlannerTurn(tool_calls=[PlannerToolCall(
            "repair", "repair_tex", {"latex": r"\frac{x}{2"},
        )]), PlannerTurn(content=r"\frac{x}{2}")], r"\frac{x}{2}"),
    ]
    rows = []
    for case_id, turns, reference in cases:
        for projected in (False, True):
            class ReplayPlanner:
                def __init__(self, trajectory):
                    self.turns = copy.deepcopy(trajectory)
                    self.calls = 0
                    self.request_bytes = []

                async def plan(self, messages, tools):
                    self.calls += 1
                    self.request_bytes.append(len(json.dumps(messages).encode()))
                    return self.turns.pop(0)

                @staticmethod
                def extract_latex(content):
                    return content

            with tempfile.TemporaryDirectory() as directory:
                # Explicit public fixture: no desktop JSON/env settings or secrets are read.
                config = TeXadaConfig.model_construct(
                    data_dir=Path(directory), failure_context_projection=projected,
                    backend="openai_compatible", openai_base_url="https://api.modelbest.cn/v1",
                    openai_api_key="", openai_model_name="MiniCPM-V-4.7-1B",
                    openai_vision_model_name="MiniCPM-V-4.7-1B",
                )
                planner = ReplayPlanner(turns)
                runtime = TeXadaAgentRuntime(config, model=planner)
                runtime.backend.ensure_ready = AsyncMock(return_value=True)
                runtime.candidate_engine.propose = lambda _: None
                start = time.perf_counter()
                with collect_inference(build_inference_identity(config)) as collector:
                    result = await runtime.run("public synthetic formula request")
                signatures = [json.dumps([call["name"], call["arguments"]], sort_keys=True)
                              for step in result.trace if step["origin"] == "planner"
                              for call in step["tool_calls"]]
                rows.append({
                    "case_id": case_id, "mode": "projected" if projected else "raw",
                    "recovered": result.valid and result.committed,
                    "planner_rounds": planner.calls,
                    "repeated_proposals": len(signatures) - len(set(signatures)),
                    "input_tokens": {"status": "NOT_CHECKED", "reason": "scripted planner"},
                    "request_json_bytes": planner.request_bytes,
                    "local_runtime_ms": round((time.perf_counter()-start)*1000, 3),
                    "strict_structure": compare_structure(result.latex, reference).to_dict(),
                    "inference_fingerprint": collector.snapshot(),
                })
    return {"schema_version": 1, "scope": "scripted planner / real local tools",
            "model_requests": 0, "claim": "No model-quality or API-latency conclusion",
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(asyncio.run(compare()), ensure_ascii=False, indent=2)+"\n")
