"""Paired offline full/minimal evaluation using identical authored scenarios.

This tests runtime execution boundaries, not model selection quality. Requests
and tools are real; the planner returns scripted proposals in each wire surface.
Provider tokens/inference latency remain explicitly NOT_CHECKED.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from structural_match import compare_structure

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig


class OfflineConfig(TeXadaConfig):
    model_config = {**TeXadaConfig.model_config, "json_file": None, "json_file_encoding": None}

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Offline replays never load the user's endpoint, credentials or environment."""
        return (init_settings,)


@dataclass(frozen=True)
class Scenario:
    case_id: str
    initial: str
    reference: str
    actions: tuple[tuple[tuple[str, int | None, dict[str, Any]], ...], ...]
    expected: str = "completed"
    task: str = "nl"


SCENARIOS = (
    Scenario(
        "explicit_fraction",
        "",
        r"\frac{x+1}{3}",
        (
            (("propose_candidate", None, {"latex": r"\frac{x+1}{3}"}),),
            (("compile_tex", 1, {"latex": r"\frac{x+1}{3}"}),),
            (("render_math", 1, {"latex": r"\frac{x+1}{3}"}),),
        ),
    ),
    Scenario(
        "deterministic_repair",
        r"\frac{x+1}{3",
        r"\frac{x+1}{3}",
        (
            (("repair_tex", 1, {"latex": r"\frac{x+1}{3"}),),
            (("compile_tex", 2, {"latex": r"\frac{x+1}{3}"}),),
            (("render_math", 2, {"latex": r"\frac{x+1}{3}"}),),
        ),
    ),
    Scenario(
        "parent_current_diff",
        "x+1",
        "x+2",
        (
            (("propose_candidate", 1, {"latex": "x+2"}),),
            (
                ("semantic_diff", 2, {"before": "x+1", "after": "x+2"}),
                ("compile_tex", 2, {"latex": "x+2"}),
            ),
            (("render_math", 2, {"latex": "x+2"}),),
        ),
    ),
    Scenario("unknown_action", "", "", ((("execute_shell", None, {}),),), "rejected"),
    Scenario(
        "runtime_value_override",
        "x+1",
        "x+1",
        ((("compile_tex", 1, {"latex": "y+2", "retain_unsafe_parameters": True}),),),
        "rejected",
    ),
    Scenario(
        "mutation_then_stale_inspection",
        r"\frac{x+1}{3",
        r"\frac{x+1}{3}",
        (
            (
                ("repair_tex", 1, {"latex": r"\frac{x+1}{3"}),
                ("compile_tex", 1, {"latex": r"\frac{x+1}{3"}),
            ),
        ),
        "rejected",
    ),
    Scenario(
        "bad_render_option",
        "x+1",
        "x+1",
        ((("render_math", 1, {"latex": "x+1", "mode": "png"}),),),
        "rejected",
    ),
    Scenario(
        "state_inapplicable_render",
        "",
        "",
        ((("render_math", None, {"latex": "x+1"}),),),
        "rejected",
    ),
)


class ReplayPlanner:
    def __init__(self, scenario: Scenario, surface: str):
        self.scenario, self.surface = scenario, surface
        self.index = 0
        self.request_bytes: list[int] = []
        self.schema_bytes: list[int] = []

    async def plan(self, messages, tools):
        self.request_bytes.append(
            len(
                json.dumps(
                    {"messages": messages, "tools": tools},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
        )
        self.schema_bytes.append(len(json.dumps(tools, separators=(",", ":")).encode()))
        batch = self.scenario.actions[self.index]
        self.index += 1
        calls = []
        for name, revision, raw in batch:
            arguments = dict(raw)
            retain = arguments.pop("retain_unsafe_parameters", False)
            if self.surface == "minimal" and name != "propose_candidate" and not retain:
                arguments = {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"latex", "before", "after"}
                }
            calls.append(
                PlannerToolCall(
                    f"{self.index}:{name}",
                    name,
                    {"expected_revision": revision, **arguments},
                )
            )
        return PlannerTurn(tool_calls=calls)

    @staticmethod
    def extract_latex(content):
        return content.strip()

    async def generate_latex(self, *args, **kwargs):
        raise AssertionError("Rejected action must not fall back to a new model candidate")


async def run_paired(output: Path | None = None) -> dict:
    rows = []
    # Start the pinned parser before the timed runs; alternate pair order to
    # reduce first-run bias. These local latencies still cannot predict a provider.
    warmup = compare_structure("x+1", "x+1").status
    with tempfile.TemporaryDirectory(prefix="texada-surface-eval-") as directory:
        for index, scenario in enumerate(SCENARIOS):
            order = ("full", "minimal") if index % 2 == 0 else ("minimal", "full")
            for surface in order:
                planner = ReplayPlanner(scenario, surface)
                runtime = TeXadaAgentRuntime(
                    OfflineConfig(
                        nl_require_review=False, nl_candidate_first=False,
                        data_dir=Path(directory), planner_surface=surface
                    ),
                    model=planner,
                )
                runtime.backend.ensure_ready = AsyncMock(return_value=True)
                runtime.candidate_engine.propose = lambda _: None
                executions = []
                actual_execute = runtime.tools.execute

                async def capture(
                    name, arguments, *, executions=executions, actual_execute=actual_execute
                ):
                    executions.append({"name": name, "arguments": dict(arguments)})
                    return await actual_execute(name, arguments)

                runtime.tools.execute = capture
                result = await runtime.run(
                    "format the supplied expression",
                    _task=scenario.task,
                    _initial_candidate=scenario.initial,
                )
                rejection = next(
                    (
                        observation
                        for item in result.trace
                        for observation in item["observations"]
                        if observation["tool"] == "planner_action_mask"
                    ),
                    None,
                )
                structure = compare_structure(result.latex, scenario.reference).to_dict()
                structure.update(
                    {
                        "reference_id": scenario.case_id,
                        "reference_source": "synthetic_author_reference",
                        "reference_review_status": "agent_reviewed",
                    }
                )
                illegal_executions = sum(
                    item["name"] == "execute_shell"
                    or item["arguments"].get("latex") == "y+2"
                    or item["arguments"].get("mode") == "png"
                    or (
                        scenario.case_id == "state_inapplicable_render"
                        and item["name"] == "render_math"
                    )
                    for item in executions
                )
                if scenario.case_id == "mutation_then_stale_inspection":
                    illegal_executions += max(
                        0,
                        sum(
                            item["name"] == "compile_tex"
                            and item["arguments"].get("latex") == scenario.initial
                            for item in executions
                        )
                        - 1,
                    )  # The initial intake compile is authorized.
                rows.append(
                    {
                        "case_id": scenario.case_id,
                        "surface": surface,
                        "task": scenario.task,
                        "intent_fidelity": "NOT_CHECKED",
                        "expected_outcome": scenario.expected,
                        "completed": result.valid and result.committed,
                        "stop_reason": result.stop_reason,
                        "outcome_expected": (
                            (result.valid and result.committed)
                            if scenario.expected == "completed"
                            else bool(rejection) and not result.committed
                        ),
                        "strict_structure": structure,
                        "rejected_illegal_calls": int(bool(rejection)),
                        "rejected_argument_errors": int(
                            bool(rejection)
                            and rejection["output"]["code"]
                            in {"invalid_arguments", "bound_value_mismatch"}
                        ),
                        "rejection_code": rejection["output"]["code"] if rejection else None,
                        "executed_illegal_calls": illegal_executions,
                        "executed_tools": executions,
                        "latency_ms": result.latency_ms,
                        "latency_scope": "offline_runtime_and_local_tools_only",
                        "request_bytes": sum(planner.request_bytes),
                        "schema_bytes": sum(planner.schema_bytes),
                        "planner_turns": planner.index,
                        "provider_tokens": {"status": "NOT_CHECKED", "value": None},
                        "provider_inference_latency": {"status": "NOT_CHECKED", "value": None},
                    }
                )
    report = {
        "schema_version": 1,
        "protocol": "scripted-paired-planner-surfaces-v2",
        "reference_source": "synthetic_author_reference",
        "reference_review_status": "agent_reviewed_not_independent_human_verified",
        "pair_order": "alternating_full_first_and_minimal_first",
        "parser_warmup_status": warmup,
        "dataset_sha256": hashlib.sha256(
            json.dumps(
                [asdict(case) for case in SCENARIOS],
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "default_surface": "full",
        "rows": rows,
        "summary": {},
    }
    for surface in ("full", "minimal"):
        selected = [row for row in rows if row["surface"] == surface]
        positive = [row for row in selected if row["expected_outcome"] == "completed"]
        comparable = [
            row for row in positive if row["strict_structure"]["status"] in {"MATCH", "DIFFERENT"}
        ]
        report["summary"][surface] = {
            "cases": len(selected),
            "expected_outcomes": sum(row["outcome_expected"] for row in selected),
            "completion_rate_positive_cases": sum(row["completed"] for row in positive)
            / len(positive),
            "strict_match_rate_comparable_positive_cases": (
                sum(row["strict_structure"]["status"] == "MATCH" for row in comparable)
                / len(comparable)
                if comparable
                else None
            ),
            "strict_comparable_positive_cases": len(comparable),
            "rejected_illegal_calls": sum(row["rejected_illegal_calls"] for row in selected),
            "rejected_argument_errors": sum(row["rejected_argument_errors"] for row in selected),
            "executed_illegal_calls": sum(row["executed_illegal_calls"] for row in selected),
            "request_bytes": sum(row["request_bytes"] for row in selected),
            "schema_bytes": sum(row["schema_bytes"] for row in selected),
            "offline_runtime_latency_ms": sum(row["latency_ms"] for row in selected),
            "provider_tokens": "NOT_CHECKED",
            "provider_inference_latency": "NOT_CHECKED",
        }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_paired(args.output))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
