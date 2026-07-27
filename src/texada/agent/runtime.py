"""Planner → Tool → Observation runtime bound to MiniCPM5."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.candidates import (
    DeterministicCandidate,
    DeterministicCandidateEngine,
)
from texada.core.intent import IntentClassifier
from texada.core.model import MiniCPMModel
from texada.core.operator_guard import OperatorDriftGuard
from texada.core.symbols import SymbolEngine
from texada.render.engine import RenderEngine
from texada.semantic import SemanticParser
from texada.tools import TeXToolset, ToolObservation, ToolRouter
from texada.types import RenderMode, RenderResult

PLANNER_SYSTEM_PROMPT = """\
You are TeXada's MiniCPM5 planner for structured mathematical editing.

Your job is planning, tool selection, multi-step execution, and state tracking.
You may infer an initial candidate LaTeX expression from the user's request,
but you MUST NOT repair invalid LaTeX yourself. Use the deterministic repair_tex
tool for every syntax repair. It is a local rule tool, not another model.
The deterministic symbol translation and required operator anchors in the user
message are authoritative. Never drop or downgrade those operators.

Preferred workflow:
1. Build or identify a candidate LaTeX expression.
2. Call parse_tex when mathematical structure matters.
3. Call compile_tex to validate the candidate.
4. If compile_tex reports invalid, call repair_tex with that exact candidate.
5. Use semantic_diff when a formula changed.
6. Call render_math before finishing.
7. Return only the final bare LaTeX expression after the tools confirm it.

Tool observations contain semantic_document objects. Treat those objects as the
state passed from one step to the next. Do not invent tool names.
"""

OCR_AGENT_PROMPT = """\

This run is an OCR review task. MiniCPM-V 4.6 has already produced a candidate
LaTeX expression. The candidate is evidence from the vision model, not a final
answer. Inspect the compile_tex observation, preserve all recognized mathematical
content, use repair_tex only when validation fails, use semantic_diff after a
change, and render_math before returning the final bare LaTeX. Do not invent
symbols that are not supported by the candidate.
"""

COMPLETION_AGENT_PROMPT = """\

This run is a formula-completion review task. A deterministic rule or MiniCPM5
has already proposed a candidate. The candidate and the user's existing prefix
are authoritative. Inspect the compile_tex observation, preserve the existing
structure, use repair_tex only when validation fails, use semantic_diff after a
change, and render_math before returning the final bare LaTeX.
"""


class PlannerBackend(Protocol):
    """Narrow planner seam; MiniCPM5 remains the production implementation."""

    async def plan(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> PlannerTurn: ...

    async def generate_latex(
        self,
        user_input: str,
        intent: str,
        *,
        force_operators: list[str] | None = None,
    ) -> str: ...

    def extract_latex(self, content: str) -> str: ...


@dataclass
class AgentRunResult:
    latex: str
    valid: bool
    render: RenderResult
    semantic_document: dict[str, Any]
    trace: list[dict[str, Any]] = field(default_factory=list)
    semantic_diff: dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    latency_ms: float = 0.0
    stop_reason: str = "completed"


class TeXadaAgentRuntime:
    """Execute MiniCPM5 planner turns until a final semantic unit is ready."""

    def __init__(
        self,
        config: TeXadaConfig,
        *,
        model: PlannerBackend | None = None,
        tool_router: ToolRouter | None = None,
        backend: BackendManager | None = None,
    ):
        self.config = config
        self.model = model or MiniCPMModel(config)
        self.tools = tool_router or ToolRouter(TeXToolset(config))
        self.backend = backend or BackendManager(config)
        self.symbol_engine = SymbolEngine()
        self.operator_guard = OperatorDriftGuard()
        self.intent_classifier = IntentClassifier()
        self.candidate_engine = DeterministicCandidateEngine()
        self.parser = SemanticParser()
        self.renderer = RenderEngine(config)
        self.max_steps = config.agent_max_steps

    async def run(
        self,
        user_input: str,
        *,
        context: str = "",
        render_mode: RenderMode = RenderMode.KATEX,
        _task: str = "nl",
        _initial_candidate: str = "",
        _initial_tokens_used: int = 0,
    ) -> AgentRunResult:
        start = time.monotonic()
        initial_candidate = self.operator_guard.normalize_candidate(
            _initial_candidate
        )
        preprocessed = (
            initial_candidate
            if _task != "nl"
            else self.symbol_engine.pre_translate(user_input)
        )
        if _task == "nl":
            proposal = self.candidate_engine.propose(user_input)
            if (
                proposal
                and not self.operator_guard.check(
                    preprocessed,
                    proposal.latex,
                )
            ):
                deterministic = await self._run_deterministic_candidate(
                    proposal,
                    preprocessed=preprocessed,
                    render_mode=render_mode,
                    start=start,
                    task="nl",
                )
                if deterministic:
                    return deterministic

        await self.backend.ensure_ready()
        system_prompt = PLANNER_SYSTEM_PROMPT
        if _task == "ocr":
            system_prompt += OCR_AGENT_PROMPT
        elif _task == "completion":
            system_prompt += COMPLETION_AGENT_PROMPT
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    self._candidate_prompt(
                        _task,
                        user_input,
                        context,
                        initial_candidate,
                    )
                    if initial_candidate
                    else self._user_prompt(user_input, context, preprocessed)
                ),
            },
        ]
        trace: list[dict[str, Any]] = []
        latest_latex = initial_candidate
        semantic_diff: dict[str, Any] = {}
        tokens_used = _initial_tokens_used
        call_fingerprints: set[str] = set()
        consecutive_errors = 0
        operator_drift_attempts = 0
        halt_reason = ""
        drift_fallback_latex = ""
        intake_valid = True
        candidate_changed_by_tool = False

        if initial_candidate:
            intake_call = PlannerToolCall(
                id=f"{_task}-candidate-intake",
                name="compile_tex",
                arguments={"latex": initial_candidate},
            )
            intake_observation = await self.tools.execute(
                intake_call.name,
                intake_call.arguments,
            )
            compact_intake = self._compact_observation(intake_observation)
            intake_valid = bool(
                intake_observation.ok
                and intake_observation.output.get("valid")
            )
            trace.append(
                {
                    "step": 1,
                    "origin": "candidate_intake",
                    "content": initial_candidate,
                    "tool_calls": [self._trace_call(intake_call)],
                    "observations": [compact_intake],
                    "task": _task,
                }
            )
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": (
                            "I will inspect the supplied candidate before "
                            "deciding the next tool action."
                        ),
                        "tool_calls": [intake_call.to_openai()],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": intake_call.id,
                        "name": intake_call.name,
                        "content": json.dumps(
                            compact_intake,
                            ensure_ascii=False,
                        ),
                    },
                ]
            )

        for step_index in range(1, self.max_steps + 1):
            turn = await self.model.plan(messages, self.tools.schemas)
            tokens_used += turn.tokens_used
            trace_item: dict[str, Any] = {
                "step": len(trace) + 1,
                "origin": "planner",
                "content": turn.content,
                "tool_calls": [],
                "observations": [],
            }
            if step_index == 1:
                trace_item["preprocessed_input"] = preprocessed
                trace_item["task"] = _task
            trace.append(trace_item)

            if not turn.tool_calls:
                candidate = self.model.extract_latex(turn.content)
                if candidate:
                    normalized_candidate = (
                        self.operator_guard.normalize_candidate(candidate)
                    )
                    direct_repair_blocked = bool(
                        initial_candidate
                        and not intake_valid
                        and not candidate_changed_by_tool
                        and normalized_candidate != latest_latex
                    )
                    if direct_repair_blocked:
                        trace_item["observations"].append(
                            {
                                "tool": "runtime_policy",
                                "ok": False,
                                "output": {
                                    "candidate": normalized_candidate,
                                    "retained_candidate": latest_latex,
                                    "required_tool": "repair_tex",
                                },
                                "error": (
                                    "Planner may not directly repair an invalid "
                                    "candidate; repair_tex is required"
                                ),
                                "duration_ms": 0.0,
                            }
                        )
                    else:
                        latest_latex = normalized_candidate
                if latest_latex:
                    deterministic = self.operator_guard.restore_required_operators(
                        preprocessed,
                        latest_latex,
                    )
                    if (
                        deterministic
                        and deterministic != latest_latex
                        and not self.operator_guard.check(
                            preprocessed,
                            deterministic,
                        )
                    ):
                        trace_item["observations"].append(
                            self._deterministic_restore_observation(
                                preprocessed,
                                deterministic,
                            )
                        )
                        return await self._finalize(
                            deterministic,
                            trace=trace,
                            render_mode=render_mode,
                            semantic_diff=semantic_diff,
                            tokens_used=tokens_used,
                            start=start,
                            stop_reason="operator_drift_deterministic_restore",
                        )
                    if self.operator_guard.check(preprocessed, latest_latex):
                        drift_fallback_latex = drift_fallback_latex or latest_latex
                        operator_drift_attempts += 1
                        feedback = self._operator_drift_feedback(
                            preprocessed,
                            latest_latex,
                        )
                        trace_item["observations"].append(feedback)
                        if operator_drift_attempts >= 2:
                            halt_reason = "operator_drift_retry_limit"
                            break
                        messages.extend(
                            [
                                {"role": "assistant", "content": turn.content},
                                {
                                    "role": "user",
                                    "content": feedback["output"]["retry_instruction"],
                                },
                            ]
                        )
                        continue
                    return await self._finalize(
                        latest_latex,
                        trace=trace,
                        render_mode=render_mode,
                        semantic_diff=semantic_diff,
                        tokens_used=tokens_used,
                        start=start,
                        stop_reason="planner_final",
                    )
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [call.to_openai() for call in turn.tool_calls],
                }
            )
            render_confirmed = False
            for call in turn.tool_calls:
                call = self._normalize_call(call)
                trace_item["tool_calls"].append(self._trace_call(call))
                fingerprint = self._call_fingerprint(call)
                if fingerprint in call_fingerprints:
                    observation = ToolObservation(
                        name=call.name,
                        ok=False,
                        error="Repeated identical tool call blocked by the Agent Runtime",
                    )
                    halt_reason = "repeated_tool_call"
                else:
                    call_fingerprints.add(fingerprint)
                    observation = await self.tools.execute(call.name, call.arguments)
                observation_data = self._compact_observation(observation)
                trace_item["observations"].append(observation_data)
                latest_latex = self._latest_latex(latest_latex, observation)
                if call.name == "semantic_diff" and observation.ok:
                    semantic_diff = observation.output
                if call.name == "repair_tex" and observation.ok:
                    semantic_diff = observation.output.get("semantic_diff", semantic_diff)
                    candidate_changed_by_tool = True
                if call.name == "render_math" and observation.ok:
                    render_confirmed = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(observation_data, ensure_ascii=False),
                    }
                )
                if observation.ok:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                if halt_reason or consecutive_errors >= 2:
                    halt_reason = halt_reason or "tool_error_limit"
                    break
            if halt_reason:
                break
            if latest_latex:
                deterministic = self.operator_guard.restore_required_operators(
                    preprocessed,
                    latest_latex,
                )
                if (
                    deterministic
                    and deterministic != latest_latex
                    and not self.operator_guard.check(preprocessed, deterministic)
                ):
                    trace_item["observations"].append(
                        self._deterministic_restore_observation(
                            preprocessed,
                            deterministic,
                        )
                    )
                    return await self._finalize(
                        deterministic,
                        trace=trace,
                        render_mode=render_mode,
                        semantic_diff=semantic_diff,
                        tokens_used=tokens_used,
                        start=start,
                        stop_reason="operator_drift_deterministic_restore",
                    )
            if latest_latex and self.operator_guard.check(preprocessed, latest_latex):
                drift_fallback_latex = drift_fallback_latex or latest_latex
                operator_drift_attempts += 1
                feedback = self._operator_drift_feedback(preprocessed, latest_latex)
                trace_item["observations"].append(feedback)
                if operator_drift_attempts >= 2:
                    halt_reason = "operator_drift_retry_limit"
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": feedback["output"]["retry_instruction"],
                    }
                )
                continue
            if render_confirmed and latest_latex:
                return await self._finalize(
                    latest_latex,
                    trace=trace,
                    render_mode=render_mode,
                    semantic_diff=semantic_diff,
                    tokens_used=tokens_used,
                    start=start,
                    stop_reason="render_confirmed",
                )

        if not latest_latex:
            forced = self.operator_guard.forced_operators(preprocessed)
            deterministic = self.operator_guard.restore_required_operators(
                preprocessed,
                "",
            )
            if forced and deterministic and not self.operator_guard.check(
                preprocessed,
                deterministic,
            ):
                latest_latex = deterministic
                halt_reason = "operator_drift_deterministic_restore"
                observation = self._deterministic_restore_observation(
                    preprocessed,
                    deterministic,
                )
            else:
                latest_latex = await self.model.generate_latex(preprocessed, "generic")
                tokens_used += self._consume_model_tokens()
                latest_latex = self.operator_guard.normalize_candidate(latest_latex)
                observation = None
            trace.append(
                {
                    "step": len(trace) + 1,
                    "origin": (
                        "deterministic_anchor_fallback"
                        if observation
                        else "compatibility_fallback"
                    ),
                    "content": latest_latex,
                    "tool_calls": [],
                    "observations": [observation] if observation else [],
                }
            )
        if self.operator_guard.check(preprocessed, latest_latex):
            forced = self.operator_guard.forced_operators(preprocessed)
            intent = self.intent_classifier.classify(user_input).intent
            constrained = await self.model.generate_latex(
                preprocessed,
                intent,
                force_operators=forced,
            )
            tokens_used += self._consume_model_tokens()
            constrained = self.operator_guard.normalize_candidate(constrained)
            recovered = bool(
                constrained
                and not self.operator_guard.check(preprocessed, constrained)
            )
            trace.append(
                {
                    "step": len(trace) + 1,
                    "origin": "operator_drift_fallback",
                    "content": constrained,
                    "tool_calls": [],
                    "observations": [
                        {
                            "tool": "operator_drift_guard",
                            "ok": recovered,
                            "output": {
                                "required_operators": forced,
                                "candidate": constrained,
                            },
                            "error": "" if recovered else "operator drift remains",
                            "duration_ms": 0.0,
                        }
                    ],
                }
            )
            if recovered:
                latest_latex = constrained
                halt_reason = "operator_drift_recovered"
            else:
                fallback = drift_fallback_latex or latest_latex
                restored = self.operator_guard.restore_required_operators(
                    preprocessed,
                    fallback,
                )
                if restored and not self.operator_guard.check(preprocessed, restored):
                    latest_latex = restored
                    halt_reason = "operator_drift_deterministic_restore"
                    trace[-1]["observations"].append(
                        self._deterministic_restore_observation(
                            preprocessed,
                            restored,
                        )
                    )
                else:
                    latest_latex = fallback
                    halt_reason = halt_reason or "operator_drift_unresolved"
        return await self._finalize(
            latest_latex,
            trace=trace,
            render_mode=render_mode,
            semantic_diff=semantic_diff,
            tokens_used=tokens_used,
            start=start,
            stop_reason=halt_reason or "max_steps_or_empty_final",
        )

    async def run_candidate(
        self,
        task: str,
        user_input: str,
        candidate_latex: str,
        *,
        context: str = "",
        render_mode: RenderMode = RenderMode.KATEX,
        initial_tokens_used: int = 0,
    ) -> AgentRunResult:
        """Run OCR/completion candidates through the shared MiniCPM5 planner."""
        if task not in {"ocr", "completion"}:
            raise ValueError("candidate task must be 'ocr' or 'completion'")
        if not candidate_latex.strip():
            raise RuntimeError(f"{task} candidate is empty")
        normalized_candidate = self.operator_guard.normalize_candidate(
            candidate_latex
        )
        if task == "completion" and initial_tokens_used == 0:
            deterministic = await self._run_deterministic_candidate(
                DeterministicCandidate(
                    latex=normalized_candidate,
                    rule="completion_deterministic",
                ),
                preprocessed=normalized_candidate,
                render_mode=render_mode,
                start=time.monotonic(),
                task="completion",
            )
            if deterministic:
                return deterministic
        return await self.run(
            user_input,
            context=context,
            render_mode=render_mode,
            _task=task,
            _initial_candidate=candidate_latex,
            _initial_tokens_used=initial_tokens_used,
        )

    async def _run_deterministic_candidate(
        self,
        proposal: DeterministicCandidate,
        *,
        preprocessed: str,
        render_mode: RenderMode,
        start: float,
        task: str,
    ) -> AgentRunResult | None:
        """Validate and render a high-confidence candidate without model inference."""
        compile_call = PlannerToolCall(
            id="deterministic-candidate-compile",
            name="compile_tex",
            arguments={"latex": proposal.latex},
        )
        compile_observation = await self.tools.execute(
            compile_call.name,
            compile_call.arguments,
        )
        valid = bool(
            compile_observation.ok
            and compile_observation.output.get("valid")
        )
        if not valid:
            return None

        render_call = PlannerToolCall(
            id="deterministic-candidate-render",
            name="render_math",
            arguments={
                "latex": proposal.latex,
                "mode": render_mode.value,
            },
        )
        render_observation = await self.tools.execute(
            render_call.name,
            render_call.arguments,
        )
        if not render_observation.ok:
            return None

        trace = [
            {
                "step": 1,
                "origin": "deterministic_candidate",
                "content": proposal.latex,
                "tool_calls": [
                    self._trace_call(compile_call),
                    self._trace_call(render_call),
                ],
                "observations": [
                    self._compact_observation(compile_observation),
                    self._compact_observation(render_observation),
                ],
                "preprocessed_input": preprocessed,
                "task": task,
                "candidate_rule": proposal.rule,
            }
        ]
        render_result = self.renderer.render(
            proposal.latex,
            mode_override=render_mode,
        )
        document = self.parser.parse(proposal.latex).to_dict()
        return AgentRunResult(
            latex=proposal.latex,
            valid=True,
            render=render_result,
            semantic_document=document,
            trace=trace,
            tokens_used=0,
            latency_ms=(time.monotonic() - start) * 1000,
            stop_reason="deterministic_candidate",
        )

    async def _finalize(
        self,
        latex: str,
        *,
        trace: list[dict[str, Any]],
        render_mode: RenderMode,
        semantic_diff: dict[str, Any],
        tokens_used: int,
        start: float,
        stop_reason: str,
    ) -> AgentRunResult:
        observations: list[dict[str, Any]] = []
        compile_observation = await self.tools.execute("compile_tex", {"latex": latex})
        observations.append(self._compact_observation(compile_observation))
        valid = bool(compile_observation.output.get("valid")) if compile_observation.ok else False

        if not valid:
            repair = await self.tools.execute("repair_tex", {"latex": latex})
            observations.append(self._compact_observation(repair))
            if repair.ok:
                latex = repair.output.get("latex", latex)
                semantic_diff = repair.output.get("semantic_diff", semantic_diff)
                valid = bool(repair.output.get("valid"))
            recompile = await self.tools.execute("compile_tex", {"latex": latex})
            observations.append(self._compact_observation(recompile))
            if recompile.ok:
                valid = bool(recompile.output.get("valid"))

        render = await self.tools.execute(
            "render_math",
            {"latex": latex, "mode": render_mode.value},
        )
        observations.append(self._compact_observation(render))
        trace.append(
            {
                "step": len(trace) + 1,
                "origin": "runtime_guard",
                "content": "",
                "tool_calls": [],
                "observations": observations,
            }
        )

        render_result = self.renderer.render(latex, mode_override=render_mode)
        document = self.parser.parse(latex).to_dict()
        return AgentRunResult(
            latex=latex,
            valid=valid,
            render=render_result,
            semantic_document=document,
            trace=trace,
            semantic_diff=semantic_diff,
            tokens_used=tokens_used,
            latency_ms=(time.monotonic() - start) * 1000,
            stop_reason=stop_reason,
        )

    @classmethod
    def _compact_observation(cls, observation: ToolObservation) -> dict[str, Any]:
        """Keep planner/log observations structural without duplicating render payloads."""
        data = observation.to_dict()
        output = data.get("output")
        if isinstance(output, dict):
            data["output"] = cls._compact_output(output)
        return data

    @classmethod
    def _compact_output(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._compact_output(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "root" in value and "parser_backend" in value:
            return {
                "schema_version": value.get("schema_version", 1),
                "latex": value.get("latex", ""),
                "parser_backend": value.get("parser_backend", ""),
                "root": cls._compact_semantic_unit(value.get("root", {})),
                "diagnostics": value.get("diagnostics", []),
            }

        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"katex_html", "latex_highlighted"}:
                continue
            compact[key] = cls._compact_output(item)
        return compact

    @classmethod
    def _compact_semantic_unit(cls, unit: Any) -> dict[str, Any]:
        if not isinstance(unit, dict):
            return {}
        compact = {"kind": unit.get("kind", "")}
        for key in ("value", "role"):
            if unit.get(key):
                compact[key] = unit[key]
        if unit.get("attributes"):
            compact["attributes"] = unit["attributes"]
        children = unit.get("children") or []
        if children:
            compact["children"] = [
                cls._compact_semantic_unit(child)
                for child in children
            ]
        return compact

    @staticmethod
    def _user_prompt(user_input: str, context: str, preprocessed: str) -> str:
        sections = []
        if context:
            sections.append(f"Context:\n{context}")
        sections.append(f"User request:\n{user_input}")
        if preprocessed != user_input:
            sections.append(
                "Deterministic symbol translation (authoritative):\n"
                f"{preprocessed}"
            )
        return "\n\n".join(sections)

    @staticmethod
    def _candidate_prompt(
        task: str,
        user_input: str,
        context: str,
        candidate_latex: str,
    ) -> str:
        label = "OCR" if task == "ocr" else "completion"
        sections = [f"Task: {label} candidate review"]
        if context:
            sections.append(f"Existing context:\n{context}")
        if user_input:
            sections.append(f"Source description or partial input:\n{user_input}")
        sections.append(
            "Candidate LaTeX (authoritative starting state):\n"
            f"{candidate_latex}"
        )
        sections.append(
            "Continue from the compile_tex observation already attached to "
            "this conversation. Choose the next tool or return the confirmed "
            "final bare LaTeX."
        )
        return "\n\n".join(sections)

    @staticmethod
    def _trace_call(call: PlannerToolCall) -> dict[str, Any]:
        return {
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }

    @staticmethod
    def _call_fingerprint(call: PlannerToolCall) -> str:
        arguments = json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"{call.name}:{arguments}"

    def _normalize_call(self, call: PlannerToolCall) -> PlannerToolCall:
        arguments = dict(call.arguments)
        for key in ("latex", "before", "after"):
            value = arguments.get(key)
            if isinstance(value, str):
                arguments[key] = self.operator_guard.normalize_candidate(value)
        if call.name == "render_math":
            mode = arguments.get("mode")
            if isinstance(mode, str) and mode.strip().lower() in {
                "katex",
                "latex",
            }:
                arguments["mode"] = mode.strip().lower()
        return PlannerToolCall(
            id=call.id,
            name=call.name,
            arguments=arguments,
        )

    def _operator_drift_feedback(
        self,
        preprocessed: str,
        candidate: str,
    ) -> dict[str, Any]:
        forced = self.operator_guard.forced_operators(preprocessed)
        rendered = ", ".join(forced)
        instruction = (
            "Runtime guard rejected the candidate because a deterministic "
            f"operator anchor was lost or downgraded. The next candidate MUST "
            f"preserve these operators exactly: {rendered}. Use tools again "
            "if validation or repair is needed."
        )
        return {
            "tool": "operator_drift_guard",
            "ok": False,
            "output": {
                "candidate": candidate,
                "required_operators": forced,
                "retry_instruction": instruction,
            },
            "error": "operator anchor lost or downgraded",
            "duration_ms": 0.0,
        }

    def _deterministic_restore_observation(
        self,
        preprocessed: str,
        candidate: str,
    ) -> dict[str, Any]:
        return {
            "tool": "operator_drift_guard",
            "ok": True,
            "output": {
                "required_operators": self.operator_guard.forced_operators(
                    preprocessed
                ),
                "candidate": candidate,
                "method": "deterministic_integral_rank_restore",
            },
            "error": "",
            "duration_ms": 0.0,
        }

    def _latest_latex(self, current: str, observation: ToolObservation) -> str:
        if not observation.ok:
            return current
        latex = observation.output.get("latex")
        if isinstance(latex, str) and latex.strip():
            return self.operator_guard.normalize_candidate(latex)
        document = observation.output.get("semantic_document")
        if isinstance(document, dict):
            latex = document.get("latex")
            if isinstance(latex, str) and latex.strip():
                return self.operator_guard.normalize_candidate(latex)
        return current

    def _consume_model_tokens(self) -> int:
        consume = getattr(self.model, "consume_tokens_used", None)
        if not callable(consume):
            return 0
        return int(consume() or 0)
