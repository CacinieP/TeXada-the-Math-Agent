"""The paired report must distinguish failed-safe actions from completions."""

import pytest
from run_planner_surface import run_paired


@pytest.mark.asyncio
async def test_paired_replay_covers_structure_execution_and_unknown_metrics(tmp_path):
    report = await run_paired(tmp_path / "paired.json")
    assert report["protocol"] == "scripted-paired-planner-surfaces-v2"
    assert len(report["rows"]) == 16
    for surface in ("full", "minimal"):
        summary = report["summary"][surface]
        assert summary["cases"] == summary["expected_outcomes"] == 8
        assert summary["completion_rate_positive_cases"] == 1
        assert summary["strict_comparable_positive_cases"] == 3
        assert summary["strict_match_rate_comparable_positive_cases"] == 1
        assert summary["rejected_illegal_calls"] == 5
        assert summary["rejected_argument_errors"] == 2
        assert summary["executed_illegal_calls"] == 0
        assert summary["provider_tokens"] == "NOT_CHECKED"
        assert summary["provider_inference_latency"] == "NOT_CHECKED"
    assert report["summary"]["minimal"]["schema_bytes"] < report["summary"]["full"]["schema_bytes"]
    rejected = [row for row in report["rows"] if row["expected_outcome"] == "rejected"]
    assert all(not row["completed"] for row in rejected)
    assert all(row["provider_tokens"]["value"] is None for row in report["rows"])
    assert all(row["task"] == "nl" and row["intent_fidelity"] == "NOT_CHECKED"
               for row in report["rows"])
    stale = [row for row in rejected if row["case_id"] == "mutation_then_stale_inspection"]
    assert all(row["rejection_code"] == "stale_revision" for row in stale)
    assert all([call["name"] for call in row["executed_tools"]] == ["compile_tex", "repair_tex"]
               for row in stale)
