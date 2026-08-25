"""Planner → Tool → Observation runtime bound to MiniCPM5."""

from __future__ import annotations

import json
import re
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
from texada.runtime import CommitBarrierError, FormulaState
from texada.semantic import SemanticParser
from texada.semantic.model import SemanticDepthError
from texada.tools import TeXToolset, ToolObservation, ToolRouter
from texada.types import RenderMode, RenderResult

PLANNER_SYSTEM_PROMPT = """\
You are TeXada's MiniCPM5 planner for structured mathematical editing.

Your job is planning, tool selection, and multi-step execution. The Formula
Runtime owns the authoritative formula state and revision history.
You may infer an initial candidate LaTeX expression from the user's request,
but you MUST NOT repair invalid LaTeX yourself. Use the deterministic repair_tex
tool for every syntax repair. It is a local rule tool, not another model.
The deterministic symbol translation and required operator anchors in the user
message are authoritative. Never drop or downgrade those operators.

Syntax validity is necessary but not sufficient. Before choosing a tool, make
an inventory of every requested operator, variable, Greek symbol, subscript,
superscript, delimiter, matrix row, and piecewise branch. Preserve that
structure exactly. Do not replace LaTeX commands with ASCII words such as
``frac``, ``sum``, ``int``, ``tan``, ``beta``, or ``nu``. Do not silently
simplify notation, change explicit to implicit multiplication, change matrix or
interval delimiters, or substitute a related formula for the requested one.
Never place a paraphrase such as ``transpose of S`` inside ``\text{...}``;
text commands are only for literal labels the user requested, such as
``otherwise`` in a cases expression.

Preferred workflow:
1. Build or identify a candidate LaTeX expression.
2. Call parse_tex when mathematical structure matters.
3. Call compile_tex to validate the candidate.
4. If compile_tex reports invalid, call repair_tex with that exact candidate.
5. Use semantic_diff when a formula changed.
6. Call render_math before finishing.
7. Return only the final bare LaTeX expression after the tools confirm it.

Tool observations are evidence for the revision shown in the observation. Their
semantic_document objects describe structure but are not mutable state owned by
you. Do not invent tool names.
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
    revision: int | None = None
    committed: bool = False
    formula_ledger: dict[str, Any] = field(default_factory=dict)


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
        self.tools = tool_router or ToolRouter(
            TeXToolset(config),
            timeout_seconds=config.tool_timeout_seconds,
        )
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
        formula_state = FormulaState(
            initial_candidate,
            origin=f"{_task}_candidate",
        )
        if _task == "nl":
            proposal = self.candidate_engine.propose(user_input)
            if (
                proposal
                and not self.operator_guard.check(
                    preprocessed,
                    proposal.latex,
                    user_input=user_input,
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
                    else self._user_prompt(
                        user_input,
                        context,
                        preprocessed,
                        self.operator_guard.forced_operators(
                            preprocessed,
                            user_input,
                        ),
                    )
                ),
            },
        ]
        trace: list[dict[str, Any]] = []
        semantic_diff: dict[str, Any] = {}
        tokens_used = _initial_tokens_used
        call_fingerprints: set[str] = set()
        consecutive_errors = 0
        operator_drift_attempts = 0
        halt_reason = ""
        drift_fallback_revision: int | None = None
        intake_valid = True
        candidate_changed_by_tool = False

        def reject_model_budget() -> AgentRunResult:
            return self._runtime_rejection(
                latex=formula_state.latex,
                trace=trace,
                render_mode=render_mode,
                semantic_diff=semantic_diff,
                tokens_used=tokens_used,
                start=start,
                stop_reason="runtime_budget_exhausted",
                formula_state=formula_state,
                observation={
                    "tool": "runtime_policy",
                    "ok": False,
                    "output": {
                        "candidate": formula_state.latex,
                        "api_request_timeout_seconds": (
                            self.config.api_request_timeout_seconds
                        ),
                        "inference_timeout_seconds": (
                            self.config.inference_timeout_seconds
                        ),
                    },
                    "error": (
                        "not enough request budget remains for another model call; "
                        "candidate was not committed"
                    ),
                    "duration_ms": 0.0,
                    "revision": formula_state.revision,
                },
            )

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
            compact_intake = self._record_formula_evidence(
                formula_state,
                intake_observation,
                revision=formula_state.revision,
            )
            planner_intake = self._planner_observation(compact_intake)
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
                            planner_intake,
                            ensure_ascii=False,
                        ),
                    },
                ]
            )

        for step_index in range(1, self.max_steps + 1):
            if not self._model_call_budget_available(start):
                return reject_model_budget()
            try:
                turn = await self.model.plan(messages, self.tools.schemas)
            except RuntimeError as exc:
                trace.append(
                    {
                        "step": len(trace) + 1,
                        "origin": "planner_error",
                        "content": formula_state.latex,
                        "tool_calls": [],
                        "observations": [
                            {
                                "tool": "model_runtime",
                                "ok": False,
                                "output": {"candidate": formula_state.latex},
                                "error": str(exc),
                                "duration_ms": 0.0,
                                "revision": formula_state.revision,
                            }
                        ],
                    }
                )
                tokens_used += self._consume_model_tokens()
                return self._runtime_rejection(
                    latex=formula_state.latex,
                    trace=trace,
                    render_mode=render_mode,
                    semantic_diff=semantic_diff,
                    tokens_used=tokens_used,
                    start=start,
                    stop_reason="model_request_failed",
                    formula_state=formula_state,
                    observation={
                        "tool": "runtime_policy",
                        "ok": False,
                        "output": {"candidate": formula_state.latex},
                        "error": "model request failed; candidate was not committed",
                        "duration_ms": 0.0,
                        "revision": formula_state.revision,
                    },
                )
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
                        and normalized_candidate != formula_state.latex
                    )
                    if direct_repair_blocked:
                        trace_item["observations"].append(
                            {
                                "tool": "runtime_policy",
                                "ok": False,
                                "output": {
                                    "candidate": normalized_candidate,
                                    "retained_candidate": formula_state.latex,
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
                        self._adopt_formula(
                            formula_state,
                            normalized_candidate,
                            origin="planner_final",
                        )
                if formula_state.latex:
                    deterministic = self.operator_guard.restore_required_operators(
                        preprocessed,
                        formula_state.latex,
                    )
                    if (
                        deterministic
                        and deterministic != formula_state.latex
                        and not self.operator_guard.check(
                            preprocessed,
                            deterministic,
                            user_input=user_input,
                        )
                    ):
                        trace_item["observations"].append(
                            self._deterministic_restore_observation(
                                preprocessed,
                                deterministic,
                                user_input=user_input,
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
                            formula_state=formula_state,
                            preprocessed=preprocessed,
                            user_input=user_input,
                        )
                    if self.operator_guard.check(
                        preprocessed,
                        formula_state.latex,
                        user_input=user_input,
                    ):
                        drift_fallback_revision = (
                            drift_fallback_revision or formula_state.revision
                        )
                        operator_drift_attempts += 1
                        feedback = self._operator_drift_feedback(
                            preprocessed,
                            formula_state.latex,
                            user_input=user_input,
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
                        formula_state.latex,
                        trace=trace,
                        render_mode=render_mode,
                        semantic_diff=semantic_diff,
                        tokens_used=tokens_used,
                        start=start,
                        stop_reason="planner_final",
                        formula_state=formula_state,
                        preprocessed=preprocessed,
                        user_input=user_input,
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
                evidence_revision = self._prepare_tool_state(
                    formula_state,
                    call,
                )
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
                observation_data = self._record_formula_evidence(
                    formula_state,
                    observation,
                    revision=evidence_revision,
                )
                trace_item["observations"].append(observation_data)
                observed_latex = self._latest_latex(
                    formula_state.latex,
                    call.name,
                    observation,
                )
                self._adopt_formula(
                    formula_state,
                    observed_latex,
                    origin=f"tool:{call.name}",
                )
                observation_data["formula_state"] = (
                    formula_state.planner_projection()
                )
                planner_observation = self._planner_observation(
                    observation_data
                )
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
                        "content": json.dumps(
                            planner_observation,
                            ensure_ascii=False,
                        ),
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
            if formula_state.latex:
                deterministic = self.operator_guard.restore_required_operators(
                    preprocessed,
                    formula_state.latex,
                )
                if (
                    deterministic
                    and deterministic != formula_state.latex
                    and not self.operator_guard.check(
                        preprocessed,
                        deterministic,
                        user_input=user_input,
                    )
                ):
                    trace_item["observations"].append(
                        self._deterministic_restore_observation(
                            preprocessed,
                            deterministic,
                            user_input=user_input,
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
                        formula_state=formula_state,
                        preprocessed=preprocessed,
                        user_input=user_input,
                    )
            if formula_state.latex and self.operator_guard.check(
                preprocessed,
                formula_state.latex,
                user_input=user_input,
            ):
                drift_fallback_revision = (
                    drift_fallback_revision or formula_state.revision
                )
                operator_drift_attempts += 1
                feedback = self._operator_drift_feedback(
                    preprocessed,
                    formula_state.latex,
                    user_input=user_input,
                )
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
            if render_confirmed and formula_state.latex:
                return await self._finalize(
                    formula_state.latex,
                    trace=trace,
                    render_mode=render_mode,
                    semantic_diff=semantic_diff,
                    tokens_used=tokens_used,
                    start=start,
                    stop_reason="render_confirmed",
                    formula_state=formula_state,
                    preprocessed=preprocessed,
                    user_input=user_input,
                )

        if not formula_state.latex:
            forced = self.operator_guard.forced_operators(
                preprocessed,
                user_input,
            )
            deterministic = self.operator_guard.restore_required_operators(
                preprocessed,
                "",
            )
            if forced and deterministic and not self.operator_guard.check(
                preprocessed,
                deterministic,
                user_input=user_input,
            ):
                self._adopt_formula(
                    formula_state,
                    deterministic,
                    origin="deterministic_anchor_fallback",
                )
                halt_reason = "operator_drift_deterministic_restore"
                observation = self._deterministic_restore_observation(
                    preprocessed,
                    deterministic,
                    user_input=user_input,
                )
            else:
                intent = self.intent_classifier.classify(user_input).intent
                if not self._model_call_budget_available(start):
                    return reject_model_budget()
                try:
                    generated_latex = await self.model.generate_latex(
                        preprocessed,
                        intent,
                    )
                except RuntimeError as exc:
                    tokens_used += self._consume_model_tokens()
                    return self._runtime_rejection(
                        latex=formula_state.latex,
                        trace=trace,
                        render_mode=render_mode,
                        semantic_diff=semantic_diff,
                        tokens_used=tokens_used,
                        start=start,
                        stop_reason="model_request_failed",
                        formula_state=formula_state,
                        observation={
                            "tool": "model_runtime",
                            "ok": False,
                            "output": {"candidate": formula_state.latex},
                            "error": str(exc),
                            "duration_ms": 0.0,
                            "revision": formula_state.revision,
                        },
                    )
                tokens_used += self._consume_model_tokens()
                generated_latex = self.operator_guard.normalize_candidate(
                    generated_latex
                )
                self._adopt_formula(
                    formula_state,
                    generated_latex,
                    origin="compatibility_fallback",
                )
                observation = None
            trace.append(
                {
                    "step": len(trace) + 1,
                    "origin": (
                        "deterministic_anchor_fallback"
                        if observation
                        else "compatibility_fallback"
                    ),
                    "content": formula_state.latex,
                    "tool_calls": [],
                    "observations": [observation] if observation else [],
                }
            )
        if self.operator_guard.check(
            preprocessed,
            formula_state.latex,
            user_input=user_input,
        ):
            forced = self.operator_guard.forced_operators(
                preprocessed,
                user_input,
            )
            intent = self.intent_classifier.classify(user_input).intent
            if not self._model_call_budget_available(start):
                return reject_model_budget()
            try:
                constrained = await self.model.generate_latex(
                    preprocessed,
                    intent,
                    force_operators=forced,
                )
            except RuntimeError as exc:
                tokens_used += self._consume_model_tokens()
                return self._runtime_rejection(
                    latex=formula_state.latex,
                    trace=trace,
                    render_mode=render_mode,
                    semantic_diff=semantic_diff,
                    tokens_used=tokens_used,
                    start=start,
                    stop_reason="model_request_failed",
                    formula_state=formula_state,
                    observation={
                        "tool": "model_runtime",
                        "ok": False,
                        "output": {
                            "candidate": formula_state.latex,
                            "required_operators": forced,
                        },
                        "error": str(exc),
                        "duration_ms": 0.0,
                        "revision": formula_state.revision,
                    },
                )
            tokens_used += self._consume_model_tokens()
            constrained = self.operator_guard.normalize_candidate(constrained)
            recovered = bool(
                constrained
                and not self.operator_guard.check(
                    preprocessed,
                    constrained,
                    user_input=user_input,
                )
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
                self._adopt_formula(
                    formula_state,
                    constrained,
                    origin="operator_drift_fallback",
                )
                halt_reason = "operator_drift_recovered"
            else:
                fallback = (
                    formula_state.latex_at(drift_fallback_revision)
                    if drift_fallback_revision is not None
                    else formula_state.latex
                )
                restored = self.operator_guard.restore_required_operators(
                    preprocessed,
                    fallback,
                )
                if restored and not self.operator_guard.check(
                    preprocessed,
                    restored,
                    user_input=user_input,
                ):
                    self._adopt_formula(
                        formula_state,
                        restored,
                        origin="operator_drift_restore",
                    )
                    halt_reason = "operator_drift_deterministic_restore"
                    trace[-1]["observations"].append(
                        self._deterministic_restore_observation(
                            preprocessed,
                            restored,
                            user_input=user_input,
                        )
                    )
                else:
                    self._adopt_formula(
                        formula_state,
                        fallback,
                        origin="operator_drift_unresolved",
                    )
                    halt_reason = halt_reason or "operator_drift_unresolved"
        return await self._finalize(
            formula_state.latex,
            trace=trace,
            render_mode=render_mode,
            semantic_diff=semantic_diff,
            tokens_used=tokens_used,
            start=start,
            stop_reason=halt_reason or "max_steps_or_empty_final",
            formula_state=formula_state,
            preprocessed=preprocessed,
            user_input=user_input,
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

        formula_state = FormulaState(
            proposal.latex,
            origin=f"{task}_deterministic_candidate",
        )
        compile_data = self._record_formula_evidence(
            formula_state,
            compile_observation,
            revision=formula_state.revision,
        )
        render_data = self._record_formula_evidence(
            formula_state,
            render_observation,
            revision=formula_state.revision,
        )
        if formula_state.revision is None:
            return None
        formula_state.commit(expected_revision=formula_state.revision)

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
                    compile_data,
                    render_data,
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
        document = self._safe_semantic_document(proposal.latex)
        return AgentRunResult(
            latex=proposal.latex,
            valid=True,
            render=render_result,
            semantic_document=document,
            trace=trace,
            tokens_used=0,
            latency_ms=(time.monotonic() - start) * 1000,
            stop_reason="deterministic_candidate",
            revision=formula_state.revision,
            committed=formula_state.committed,
            formula_ledger=formula_state.to_dict(),
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
        formula_state: FormulaState,
        preprocessed: str = "",
        user_input: str = "",
    ) -> AgentRunResult:
        latex = self._adopt_formula(
            formula_state,
            latex,
            origin="runtime_finalize_input",
        )
        if formula_state.revision is None:
            return self._runtime_rejection(
                latex="",
                trace=trace,
                render_mode=render_mode,
                semantic_diff=semantic_diff,
                tokens_used=tokens_used,
                start=start,
                stop_reason="empty_formula_state",
                formula_state=formula_state,
                observation={
                    "tool": "runtime_policy",
                    "ok": False,
                    "output": {"candidate": ""},
                    "error": "planner and compatibility fallback produced no formula",
                    "duration_ms": 0.0,
                    "revision": None,
                },
            )

        missing = self.operator_guard.missing_requirements(
            preprocessed,
            latex,
            user_input=user_input,
        )
        if missing:
            return self._runtime_rejection(
                latex=latex,
                trace=trace,
                render_mode=render_mode,
                semantic_diff=semantic_diff,
                tokens_used=tokens_used,
                start=start,
                stop_reason="semantic_anchor_unresolved",
                formula_state=formula_state,
                observation={
                    "tool": "operator_drift_guard",
                    "ok": False,
                    "output": {
                        "candidate": latex,
                        "missing_requirements": missing,
                        "required_operators": self.operator_guard.forced_operators(
                            preprocessed,
                            user_input,
                        ),
                    },
                    "error": "required request structure remains unresolved",
                    "duration_ms": 0.0,
                    "revision": formula_state.revision,
                },
            )

        observations: list[dict[str, Any]] = []
        compile_observation = await self.tools.execute("compile_tex", {"latex": latex})
        observations.append(
            self._record_formula_evidence(
                formula_state,
                compile_observation,
                revision=formula_state.revision,
            )
        )
        valid = bool(compile_observation.output.get("valid")) if compile_observation.ok else False

        if not valid:
            repair_revision = formula_state.revision
            repair = await self.tools.execute("repair_tex", {"latex": latex})
            observations.append(
                self._record_formula_evidence(
                    formula_state,
                    repair,
                    revision=repair_revision,
                )
            )
            if repair.ok:
                latex = self._adopt_formula(
                    formula_state,
                    repair.output.get("latex", latex),
                    origin="tool:repair_tex",
                )
                semantic_diff = repair.output.get("semantic_diff", semantic_diff)
                valid = bool(repair.output.get("valid"))
            recompile = await self.tools.execute("compile_tex", {"latex": latex})
            observations.append(
                self._record_formula_evidence(
                    formula_state,
                    recompile,
                    revision=formula_state.revision,
                )
            )
            if recompile.ok:
                valid = bool(recompile.output.get("valid"))

        if not valid:
            trace.append(
                {
                    "step": len(trace) + 1,
                    "origin": "runtime_guard",
                    "content": latex,
                    "tool_calls": [],
                    "observations": observations,
                }
            )
            render_result = self.renderer.render(
                latex,
                mode_override=render_mode,
            )
            document = self._safe_semantic_document(latex)
            return AgentRunResult(
                latex=latex,
                valid=False,
                render=render_result,
                semantic_document=document,
                trace=trace,
                semantic_diff=semantic_diff,
                tokens_used=tokens_used,
                latency_ms=(time.monotonic() - start) * 1000,
                stop_reason="validation_failed_after_repair",
                revision=formula_state.revision,
                committed=False,
                formula_ledger=formula_state.to_dict(),
            )

        render = await self.tools.execute(
            "render_math",
            {"latex": latex, "mode": render_mode.value},
        )
        observations.append(
            self._record_formula_evidence(
                formula_state,
                render,
                revision=formula_state.revision,
            )
        )
        commit_error = ""
        try:
            formula_state.commit(expected_revision=formula_state.revision)
        except CommitBarrierError as exc:
            commit_error = str(exc)
            stop_reason = "commit_barrier_failed"
            observations.append(
                {
                    "tool": "commit_barrier",
                    "ok": False,
                    "output": {"revision": formula_state.revision},
                    "error": commit_error,
                    "duration_ms": 0.0,
                    "revision": formula_state.revision,
                }
            )
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
        document = self._safe_semantic_document(latex)
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
            revision=formula_state.revision,
            committed=formula_state.committed,
            formula_ledger=formula_state.to_dict(),
        )

    def _runtime_rejection(
        self,
        *,
        latex: str,
        trace: list[dict[str, Any]],
        render_mode: RenderMode,
        semantic_diff: dict[str, Any],
        tokens_used: int,
        start: float,
        stop_reason: str,
        formula_state: FormulaState,
        observation: dict[str, Any],
    ) -> AgentRunResult:
        """Return a controlled, uncommitted result for a runtime policy failure."""
        trace.append(
            {
                "step": len(trace) + 1,
                "origin": "runtime_guard",
                "content": latex,
                "tool_calls": [],
                "observations": [observation],
            }
        )
        return AgentRunResult(
            latex=latex,
            valid=False,
            render=self.renderer.render(latex, mode_override=render_mode),
            semantic_document=self._safe_semantic_document(latex),
            trace=trace,
            semantic_diff=semantic_diff,
            tokens_used=tokens_used,
            latency_ms=(time.monotonic() - start) * 1000,
            stop_reason=stop_reason,
            revision=formula_state.revision,
            committed=False,
            formula_ledger=formula_state.to_dict(),
        )

    @classmethod
    def _compact_observation(cls, observation: ToolObservation) -> dict[str, Any]:
        """Keep planner/log observations structural without duplicating render payloads."""
        data = observation.to_dict()
        output = data.get("output")
        if isinstance(output, dict):
            data["output"] = cls._compact_output(output)
        return data

    def _record_formula_evidence(
        self,
        formula_state: FormulaState,
        observation: ToolObservation,
        *,
        revision: int | None,
    ) -> dict[str, Any]:
        """Bind a tool observation to the exact formula revision it inspected."""
        data = self._compact_observation(observation)
        data["revision"] = revision
        if revision is not None:
            formula_state.add_evidence(
                revision=revision,
                kind=observation.name,
                ok=observation.ok,
                output=data.get("output", {}),
                error=observation.error,
            )
        data["formula_state"] = formula_state.planner_projection()
        return data

    @staticmethod
    def _adopt_formula(
        formula_state: FormulaState,
        latex: Any,
        *,
        origin: str,
    ) -> str:
        """Accept a candidate through the state authority and return its value."""
        if not isinstance(latex, str) or not latex.strip():
            return formula_state.latex
        formula_state.revise(
            latex,
            expected_revision=formula_state.revision,
            origin=origin,
        )
        return formula_state.latex

    def _prepare_tool_state(
        self,
        formula_state: FormulaState,
        call: PlannerToolCall,
    ) -> int | None:
        """Create a revision for the formula a planner-selected tool will inspect."""
        key = "after" if call.name == "semantic_diff" else "latex"
        candidate = call.arguments.get(key)
        self._adopt_formula(
            formula_state,
            candidate,
            origin=f"planner_tool:{call.name}",
        )
        return formula_state.revision

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
    def _planner_observation(
        cls,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        """Project evidence into a bounded view without a full Semantic tree."""
        projected = {
            "tool": observation.get("tool", ""),
            "ok": bool(observation.get("ok")),
            "output": cls._planner_value(observation.get("output", {})),
            "error": observation.get("error", ""),
            "revision": observation.get("revision"),
            "formula_state": observation.get("formula_state", {}),
        }
        return projected

    @classmethod
    def _planner_value(cls, value: Any) -> Any:
        if isinstance(value, list):
            items = [cls._planner_value(item) for item in value[:32]]
            if len(value) > 32:
                items.append({"truncated_items": len(value) - 32})
            return items
        if not isinstance(value, dict):
            return value
        if "root" in value and "parser_backend" in value:
            return cls._semantic_projection(value)
        projected: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"katex_html", "latex_highlighted"}:
                continue
            projected_key = (
                "semantic_summary" if key == "semantic_document" else key
            )
            projected[projected_key] = cls._planner_value(item)
        return projected

    @classmethod
    def _semantic_projection(cls, document: dict[str, Any]) -> dict[str, Any]:
        """Summarize a SemanticDocument without exposing its mutable full tree."""
        root = document.get("root")
        stack = [root] if isinstance(root, dict) else []
        kinds: set[str] = set()
        roles: set[str] = set()
        node_count = 0
        truncated = False
        while stack:
            unit = stack.pop()
            node_count += 1
            if node_count > 64:
                truncated = True
                break
            kind = unit.get("kind")
            role = unit.get("role")
            if isinstance(kind, str) and kind:
                kinds.add(kind)
            if isinstance(role, str) and role:
                roles.add(role)
            children = unit.get("children")
            if isinstance(children, list):
                stack.extend(
                    child for child in children if isinstance(child, dict)
                )
        return {
            "schema_version": document.get("schema_version", 1),
            "parser_backend": document.get("parser_backend", ""),
            "root_kind": root.get("kind", "") if isinstance(root, dict) else "",
            "node_count": min(node_count, 64),
            "kinds": sorted(kinds),
            "roles": sorted(roles),
            "diagnostics": document.get("diagnostics", []),
            "truncated": truncated,
        }

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
    def _user_prompt(
        user_input: str,
        context: str,
        preprocessed: str,
        required_anchors: list[str] | None = None,
    ) -> str:
        sections = []
        if context:
            sections.append(f"Context:\n{context}")
        sections.append(f"User request:\n{user_input}")
        if preprocessed != user_input:
            sections.append(
                "Deterministic symbol translation (authoritative):\n"
                f"{preprocessed}"
            )
        if required_anchors:
            sections.append(
                "Runtime request anchors (all must appear in equivalent "
                "LaTeX structure):\n"
                + "\n".join(f"- {anchor}" for anchor in required_anchors)
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
                arguments[key] = self._sanitize_latex_argument(value)
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

    def _sanitize_latex_argument(self, value: str) -> str:
        """Remove prompt labels accidentally copied into a tool argument."""
        sanitized = value.strip()
        markers = (
            "Deterministic symbol translation (authoritative):",
            "Candidate LaTeX (authoritative starting state):",
            "Candidate LaTeX:",
            "Final LaTeX:",
            "LaTeX:",
        )
        for marker in markers:
            if marker in sanitized:
                sanitized = sanitized.rsplit(marker, 1)[1].strip()
        sanitized = re.sub(
            r"^(?:formula|candidate|latex)\s*:\s*",
            "",
            sanitized,
            flags=re.IGNORECASE,
        )
        return self.operator_guard.normalize_candidate(sanitized)

    def _operator_drift_feedback(
        self,
        preprocessed: str,
        candidate: str,
        *,
        user_input: str = "",
    ) -> dict[str, Any]:
        forced = self.operator_guard.forced_operators(
            preprocessed,
            user_input,
        )
        missing = self.operator_guard.missing_requirements(
            preprocessed,
            candidate,
            user_input=user_input,
        )
        rendered = ", ".join(forced)
        instruction = (
            "Runtime guard rejected the candidate because required request "
            f"structure was lost or downgraded. The next candidate MUST "
            f"preserve these LaTeX anchors: {rendered}. Re-read the original "
            "request, restore every named symbol and delimiter, then use tools "
            "again if validation or repair is needed."
        )
        return {
            "tool": "operator_drift_guard",
            "ok": False,
            "output": {
                "candidate": candidate,
                "required_operators": forced,
                "missing_requirements": missing,
                "retry_instruction": instruction,
            },
            "error": "operator anchor lost or downgraded",
            "duration_ms": 0.0,
        }

    def _deterministic_restore_observation(
        self,
        preprocessed: str,
        candidate: str,
        *,
        user_input: str = "",
    ) -> dict[str, Any]:
        return {
            "tool": "operator_drift_guard",
            "ok": True,
            "output": {
                "required_operators": self.operator_guard.forced_operators(
                    preprocessed,
                    user_input,
                ),
                "candidate": candidate,
                "method": "deterministic_integral_rank_restore",
            },
            "error": "",
            "duration_ms": 0.0,
        }

    def _latest_latex(
        self,
        current: str,
        tool_name: str,
        observation: ToolObservation,
    ) -> str:
        if tool_name not in {"compile_tex", "repair_tex", "render_math"}:
            return current
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

    def _model_call_budget_available(self, start: float) -> bool:
        """Reserve enough wall time for the API bridge to return a response."""
        request_timeout = self.config.api_request_timeout_seconds
        inference_timeout = self.config.inference_timeout_seconds
        response_reserve = max(5.0, min(30.0, request_timeout * 0.10))
        latest_safe_start = max(
            1.0,
            request_timeout - inference_timeout - response_reserve,
        )
        return (time.monotonic() - start) < latest_safe_start

    def _safe_semantic_document(self, latex: str) -> dict[str, Any]:
        """Serialize a semantic document without ever crashing the runtime.

        The parser and serializers are depth-bounded, but this path is called
        directly (outside the tool router) so it keeps its own guard: any
        structural failure degrades to an empty document instead of a 500.
        """
        try:
            return self.parser.parse(latex).to_dict()
        except (RecursionError, SemanticDepthError):
            return {
                "schema_version": 1,
                "latex": latex,
                "parser_backend": "depth-guard",
                "root": {"kind": "sequence", "children": []},
                "diagnostics": [
                    "semantic tree exceeded structural limits"
                ],
            }
