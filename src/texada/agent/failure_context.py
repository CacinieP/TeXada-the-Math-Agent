"""Project failed tool exchanges out of the planner view, retaining raw audit data."""
from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

FAILURE_CONTEXT_INSTRUCTION = (
    "Runtime recovery context is authoritative. Use authoritative_formula for the "
    "current formula/revision. Failed argument blocks are audit history, not examples "
    "or current state. Choose the indicated recovery from the available action surface."
)
_KNOWN_TOOLS = frozenset({
    "parse_tex", "compile_tex", "repair_tex", "semantic_diff", "render_math", "export",
    "propose_candidate",
})


@dataclass
class FailureProjection:
    messages: list[dict[str, Any]]
    metrics: dict[str, Any]


def _failure(payload: Any, name: str) -> str | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        return "PROTOCOL_INCOMPLETE"
    output = payload.get("output", {})
    if not isinstance(output, dict):
        return "PROTOCOL_INCOMPLETE"
    if name == "compile_tex" and output.get("valid") is False:
        return "VALIDATION_FAILED"
    if payload["ok"]:
        return None
    # Only host-authored enums are recognized. Raw errors never enter recovery context.
    category = payload.get("failure_kind")
    if category in {"ARGUMENT_ERROR", "TIMEOUT", "STRUCTURAL_LIMIT", "REPEAT_BLOCKED",
                    "STALE_REVISION", "ACTION_REJECTED"}:
        return category
    return "TOOL_FAILED" if name in _KNOWN_TOOLS else "UNKNOWN_TOOL"


def project_failure_context(
    messages: list[dict[str, Any]], authoritative_state: dict[str, Any], *, enabled: bool,
) -> FailureProjection:
    """Pure projection: canonical call/observation pairs stay valid, source is untouched."""
    source = copy.deepcopy(messages)
    projected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    removed = 0
    index = 0
    while index < len(source):
        message = source[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            # Orphan observations cannot be sent to the SDK in projected mode.
            if message.get("role") != "tool" or not enabled:
                projected.append(message)
            index += 1
            continue
        calls = message["tool_calls"]
        end = index + 1
        observations = []
        while end < len(source) and source[end].get("role") == "tool":
            observations.append(source[end])
            end += 1
        ids = Counter(call.get("id") for call in calls)
        by_id: dict[str, list[dict]] = {}
        for observation in observations:
            by_id.setdefault(observation.get("tool_call_id"), []).append(observation)
        kept_calls, kept_observations = [], []
        group_failed = False
        for call in calls:
            call_id = call.get("id")
            name = call.get("function", {}).get("name", "")
            pair = by_id.get(call_id, [])
            payload = None
            if call_id and ids[call_id] == 1 and len(pair) == 1:
                try:
                    payload = json.loads(pair[0].get("content", ""))
                except (TypeError, ValueError):
                    pass
            failure_kind = _failure(payload, name)
            if failure_kind is None:
                kept_calls.append(call)
                kept_observations.extend(pair)
            else:
                group_failed = True
                removed += 1
                failures.append({
                    "failure_kind": failure_kind,
                    "tool": name if name in _KNOWN_TOOLS else "unknown_action",
                    "recovery_action": "repair_tex" if failure_kind == "VALIDATION_FAILED"
                    else "choose_available_action" if failure_kind in {
                        "UNKNOWN_TOOL", "PROTOCOL_INCOMPLETE", "ACTION_REJECTED", "STALE_REVISION",
                    } else "inspect_authoritative_state",
                })
        if not enabled:
            projected.extend(source[index:end])
        elif kept_calls:
            message["tool_calls"] = kept_calls
            if group_failed:
                # Free-form assistant text can embed the failed parameters too.
                message["content"] = "Retained successful tool actions from this turn."
            projected.append(message)
            projected.extend(kept_observations)
        index = end
    if enabled and failures:
        summary = {
            "runtime_recovery_context": {
                "instruction": FAILURE_CONTEXT_INSTRUCTION,
                "authoritative_formula": copy.deepcopy(authoritative_state),
                "failed_calls": failures,
            },
        }
        # Keep successful assistant/tool exchanges contiguous and preserve their order.
        insertion = next((i for i, item in enumerate(projected)
                          if item.get("role") == "assistant"), len(projected))
        projected.insert(insertion, {"role": "user", "content": json.dumps(
            summary, ensure_ascii=False, separators=(",", ":"),
        )})
    metrics = {
        "mode": "projected" if enabled else "raw",
        "failed_calls_removed": removed if enabled else 0,
        "failed_calls_in_history": removed,
        "failure_kinds": dict(Counter(item["failure_kind"] for item in failures)),
        "authoritative_revision": authoritative_state.get("revision"),
        "request_json_bytes": len(json.dumps(projected, ensure_ascii=False).encode()),
        "input_tokens": {"status": "NOT_CHECKED", "value": None,
                         "reason": "provider prompt-token usage not reported"},
    }
    return FailureProjection(projected, metrics)
