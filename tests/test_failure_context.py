"""Recovery projection changes the planner view, never the audit or formula authority."""
from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock

import pytest

from texada.agent.failure_context import project_failure_context
from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.inference_fingerprint import (
    build_inference_identity,
    canonical_sha256,
    collect_inference,
    validate_inference_fingerprint,
)


def call(identifier, name="compile_tex", latex="failed_argument_payload"):
    return PlannerToolCall(identifier, name, {"latex": latex}).to_openai()


def observation(identifier, *, ok=True, valid=True, name="compile_tex"):
    return {"role": "tool", "tool_call_id": identifier, "name": name,
            "content": json.dumps({"ok": ok, "output": {"valid": valid},
                                   "error": "raw private error with failed_argument_payload"})}


@pytest.mark.parametrize("ok,valid", [(False, True), (True, False)])
def test_failed_call_and_observation_removed_as_pair_not_original_history(ok, valid):
    messages = [{"role": "system", "content": "policy"}, {"role": "user", "content": "request"},
                {"role": "assistant", "content": "failed_argument_payload",
                 "tool_calls": [call("a")]},
                observation("a", ok=ok, valid=valid)]
    before = copy.deepcopy(messages)
    projected = project_failure_context(messages, {"revision": 2, "latex": "x+1"}, enabled=True)
    assert messages == before
    text = json.dumps(projected.messages)
    assert "failed_argument_payload" not in text
    assert "raw private error" not in text
    assert not any(item["role"] == "tool" for item in projected.messages)
    context = json.loads(projected.messages[-1]["content"])["runtime_recovery_context"]
    assert context["authoritative_formula"] == {"revision": 2, "latex": "x+1"}
    assert projected.metrics["failed_calls_removed"] == 1
    assert context["failed_calls"][0]["recovery_action"] == (
        "repair_tex" if valid is False else "inspect_authoritative_state")


def test_mixed_turn_keeps_only_successful_protocol_pair_and_clears_raw_assistant_text():
    messages = [{"role": "assistant", "content": "failed_argument_payload",
                 "tool_calls": [call("a"), call("b", latex="x+1")]},
                observation("a", valid=False), observation("b")]
    projected = project_failure_context(messages, {"revision": 3, "latex": "x+1"}, enabled=True)
    assistant = next(item for item in projected.messages if item["role"] == "assistant")
    assert [item["id"] for item in assistant["tool_calls"]] == ["b"]
    tools = [item for item in projected.messages if item["role"] == "tool"]
    assert [item["tool_call_id"] for item in tools] == ["b"]
    assert "failed_argument_payload" not in assistant["content"]


@pytest.mark.parametrize("tail", [[], [observation("other")], [observation("a"), observation("a")],
                                  [{"role": "tool", "tool_call_id": "a", "content": "malformed"}]])
def test_missing_duplicate_or_malformed_observations_never_leave_orphan_protocol(tail):
    messages = [{"role": "assistant", "tool_calls": [call("a")]}] + tail
    projected = project_failure_context(messages, {"revision": None, "latex": ""}, enabled=True)
    assert all(item["role"] not in {"assistant", "tool"} for item in projected.messages)
    assert projected.metrics["failure_kinds"] == {"PROTOCOL_INCOMPLETE": 1}


def test_raw_control_is_exact_deep_copy_and_unknown_names_do_not_become_instructions():
    messages = [{"role": "assistant", "tool_calls": [call("a", name="private injected action")]},
                observation("a", ok=False)]
    raw = project_failure_context(messages, {"revision": 1}, enabled=False)
    assert raw.messages == messages and raw.messages is not messages
    projected = project_failure_context(messages, {"revision": 1}, enabled=True)
    assert "private injected action" not in json.dumps(projected.messages)
    assert projected.metrics["failure_kinds"] == {"UNKNOWN_TOOL": 1}


def test_authority_can_retain_invalid_formula_without_reintroducing_failed_argument_block():
    messages = [{"role": "assistant", "tool_calls": [call("a", latex=r"\frac{x}{")]},
                observation("a", valid=False)]
    projected = project_failure_context(
        messages, {"revision": 1, "latex": r"\frac{x}{"}, enabled=True,
    )
    context = json.loads(projected.messages[0]["content"])["runtime_recovery_context"]
    assert context["authoritative_formula"]["latex"] == r"\frac{x}{"
    assert "arguments" not in context["failed_calls"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_runtime_failed_history_projection_recovers_with_raw_audit_retained(
    tmp_path, enabled,
):
    class Planner:
        def __init__(self):
            self.messages = []

        async def plan(self, messages, tools):
            self.messages.append(copy.deepcopy(messages))
            if len(self.messages) == 1:
                return PlannerTurn(tool_calls=[PlannerToolCall(
                    "failed", "unknown_action", {"invalid_key": "failed_argument_payload"},
                )], prompt_tokens_used=41)
            return PlannerTurn(content="x+1", prompt_tokens_used=53)

        @staticmethod
        def extract_latex(value):
            return value

    planner = Planner()
    runtime = TeXadaAgentRuntime(TeXadaConfig(
        data_dir=tmp_path, failure_context_projection=enabled,
    ), model=planner)
    runtime.candidate_engine.propose = lambda _: None
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run("public synthetic recovery request")
    assert result.valid and result.committed
    assert len(planner.messages) == 2
    assert ("failed_argument_payload" in json.dumps(planner.messages[1])) == (not enabled)
    assert "failed_argument_payload" in json.dumps(result.trace[0]["raw_tool_calls"])
    assert result.trace[0]["observations"][0]["ok"] is False
    assert result.trace[1]["planner_projection"]["input_tokens"] == {
        "status": "REPORTED", "value": 53, "reason": "",
    }
    assert result.trace[1]["planner_projection"]["failed_calls_removed"] == int(enabled)


def test_planner_controls_change_identity_without_invalidating_legacy_schema_one(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    identity = build_inference_identity(config)
    raw = build_inference_identity(config.model_copy(update={"failure_context_projection": False}))
    assert canonical_sha256(identity) != canonical_sha256(raw)
    with collect_inference(identity) as collector:
        recorded = collector.snapshot()
    legacy = copy.deepcopy(recorded)
    legacy["identity"].pop("planner_controls")
    legacy["identity_sha256"] = canonical_sha256(legacy["identity"])
    imported = validate_inference_fingerprint(legacy)
    assert "planner_controls" not in imported["identity"]
    assert imported["identity_sha256"] == legacy["identity_sha256"]
