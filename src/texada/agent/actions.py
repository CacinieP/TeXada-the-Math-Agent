"""Planner-only action surfaces and execution-time revision binding.

The canonical ToolRouter contracts stay independent. A planner proposes an
action against a frozen turn snapshot; only this module can bind that proposal
to the Formula Runtime's current value. No inspection tool mutates formula state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from texada.agent.protocol import PlannerToolCall
from texada.runtime import FormulaState
from texada.tools.registry import MAX_TEX_LENGTH

Surface = Literal["full", "minimal"]
INSPECTION_ACTIONS = frozenset({"parse_tex", "compile_tex", "repair_tex", "render_math", "export"})
KNOWN_ACTIONS = INSPECTION_ACTIONS | {"semantic_diff", "propose_candidate"}


class ActionRejected(ValueError):
    """A rejected planner proposal, never forwarded to a tool handler."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class ActionSnapshot:
    revision: int | None
    latex: str
    parent_revision: int | None
    before: str
    allowed: frozenset[str]

    def projection(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "latex": self.latex,
            "parent_revision": self.parent_revision,
            "allowed_actions": sorted(self.allowed),
        }


@dataclass(frozen=True)
class BoundAction:
    call: PlannerToolCall
    revision: int | None
    revision_source: str
    candidate: str = ""
    initial_seed_bridge: bool = False


def action_snapshot(state: FormulaState, *, surface: Surface) -> ActionSnapshot:
    current = state.ledger.current
    parent = current.parent if current else None
    compile_evidence = next(
        (
            item
            for item in reversed(state.ledger.evidence)
            if item.revision == state.revision and item.kind == "compile_tex"
        ),
        None,
    )
    invalid = bool(
        compile_evidence and compile_evidence.ok and compile_evidence.output.get("valid") is False
    )
    valid = bool(
        compile_evidence and compile_evidence.ok and compile_evidence.output.get("valid") is True
    )
    allowed: set[str] = set()
    if state.latex:
        allowed.update({"parse_tex", "compile_tex"})
        if invalid:
            allowed.add("repair_tex")
        else:
            allowed.add("propose_candidate")
        if valid:
            allowed.update({"render_math", "export"})
        if parent is not None:
            allowed.add("semantic_diff")
    else:
        allowed.add("propose_candidate")
        if surface == "full":
            allowed.add("compile_tex")  # Explicitly recorded legacy initial seed only.
    return ActionSnapshot(
        state.revision,
        state.latex,
        parent,
        state.latex_at(parent) if parent else "",
        frozenset(allowed),
    )


def planner_schemas(
    canonical: list[dict[str, Any]],
    snapshot: ActionSnapshot,
    *,
    surface: Surface,
) -> list[dict[str, Any]]:
    """Build a wire surface without modifying the canonical definitions."""
    result: list[dict[str, Any]] = []
    for raw in canonical:
        schema = deepcopy(raw)
        function = schema["function"]
        name = function["name"]
        if surface == "minimal" and name not in snapshot.allowed:
            continue
        parameters = function["parameters"]
        if surface == "minimal":
            properties = {
                key: value
                for key, value in parameters["properties"].items()
                if key not in {"latex", "before", "after"}
            }
            parameters["properties"] = properties
            parameters["required"] = []
            function["description"] = f"Inspect authoritative revision using {name}."
        parameters["properties"]["expected_revision"] = {
            "type": ["integer", "null"],
            "enum": [snapshot.revision],
            "description": "Revision in the action state. Never guess a newer revision.",
        }
        if surface == "minimal":
            parameters["required"].append("expected_revision")
        result.append(schema)
    if surface == "full" or "propose_candidate" in snapshot.allowed:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": "propose_candidate",
                    "description": "Explicit candidate proposal; runtime owns the new revision.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "latex": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_TEX_LENGTH,
                            },
                            "expected_revision": {
                                "type": ["integer", "null"],
                                "enum": [snapshot.revision],
                            },
                        },
                        "required": ["latex", "expected_revision"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return result


def bind_action(
    call: PlannerToolCall,
    snapshot: ActionSnapshot,
    state: FormulaState,
    *,
    surface: Surface,
) -> BoundAction:
    """Validate the immutable proposal and independently recompile the live mask."""
    if call.name not in KNOWN_ACTIONS:
        raise ActionRejected("unknown_action", f"Unknown planner action: {call.name}")
    arguments = dict(call.arguments)
    explicit = "expected_revision" in arguments
    if not explicit and (surface == "minimal" or call.name == "propose_candidate"):
        raise ActionRejected("missing_revision", "expected_revision is required")
    expected = arguments.pop("expected_revision", snapshot.revision)
    if expected is not None and (type(expected) is not int or expected < 1):
        raise ActionRejected("invalid_revision", "expected_revision must be an integer or null")
    if expected != snapshot.revision or state.revision != snapshot.revision:
        raise ActionRejected(
            "stale_revision", "Proposal no longer targets the current turn revision"
        )
    live = action_snapshot(state, surface=surface)
    if call.name not in snapshot.allowed or call.name not in live.allowed:
        raise ActionRejected("action_not_applicable", f"{call.name} is unavailable for this state")
    source = "planner_explicit" if explicit else "runtime_turn_snapshot"
    if call.name == "propose_candidate":
        if set(arguments) != {"latex"}:
            raise ActionRejected("invalid_arguments", "propose_candidate requires only latex")
        candidate = arguments["latex"]
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or len(candidate) > MAX_TEX_LENGTH
        ):
            raise ActionRejected("invalid_arguments", "Candidate must be non-empty bounded LaTeX")
        return BoundAction(call, state.revision, source, candidate=candidate.strip())
    allowed_keys = (
        {"mode"} if call.name == "render_math" else {"format"} if call.name == "export" else set()
    )
    bound_values = (
        {"before": live.before, "after": live.latex}
        if call.name == "semantic_diff"
        else {"latex": live.latex}
    )
    seed = call.name == "compile_tex" and not live.latex and surface == "full"
    if surface == "full":
        allowed_keys |= set(bound_values)
    if set(arguments) - allowed_keys:
        raise ActionRejected("invalid_arguments", "Unexpected or runtime-owned action arguments")
    if surface == "full":
        if seed:
            candidate = arguments.get("latex")
            if (
                not isinstance(candidate, str)
                or not candidate.strip()
                or len(candidate) > MAX_TEX_LENGTH
            ):
                raise ActionRejected(
                    "invalid_arguments", "Initial compile seed requires bounded LaTeX"
                )
            bound_values = {"latex": candidate.strip()}
        else:
            for key, value in bound_values.items():
                if arguments.get(key) != value:
                    raise ActionRejected(
                        "bound_value_mismatch", f"{key} is owned by the Formula Runtime"
                    )
    if "mode" in arguments and arguments["mode"] not in {"katex", "latex"}:
        raise ActionRejected("invalid_arguments", "Invalid render mode")
    if "format" in arguments and arguments["format"] not in {
        "latex",
        "inline",
        "display",
        "markdown",
    }:
        raise ActionRejected("invalid_arguments", "Invalid export format")
    options = {key: value for key, value in arguments.items() if key not in bound_values}
    return BoundAction(
        PlannerToolCall(call.id, call.name, {**options, **bound_values}),
        state.revision,
        source,
        candidate=bound_values["latex"] if seed else "",
        initial_seed_bridge=seed,
    )
