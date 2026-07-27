"""Input Router — unified entry point, dispatches to the correct pipeline."""
from __future__ import annotations

import re
import time

from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.fixer import LaTeXFixer
from texada.core.intent import IntentClassifier
from texada.core.model import MiniCPMModel
from texada.core.operator_guard import OperatorDriftGuard
from texada.core.symbols import SymbolEngine
from texada.core.validator import LaTeXValidator
from texada.render.engine import RenderEngine
from texada.store.shorthand import ShorthandStore
from texada.types import (
    ConversationTurn,
    ConvertResult,
    IntentResult,
    RenderMode,
    RenderResult,
    Route,
    Source,
    Tab,
    ValidationResult,
)


class ConversationMemory:
    """Agent Memory — keeps last N turns for context-aware generation."""

    def __init__(self, max_turns: int = 6):
        self.max_turns = max_turns
        self.turns: list[ConversationTurn] = []

    def add(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

    def to_messages(self) -> list[dict]:
        """Export as OpenAI-compatible message list."""
        messages: list[dict] = []
        for turn in self.turns:
            messages.append({"role": turn.role, "content": turn.content})
        return messages

    def clear(self) -> None:
        self.turns.clear()


class InputRouter:
    """Routes user input to the correct pipeline based on type and content."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self.intent_classifier = IntentClassifier()
        self.symbol_engine = SymbolEngine()
        self.model = MiniCPMModel(config)
        self.operator_guard = OperatorDriftGuard()
        self.validator = LaTeXValidator()
        self.fixer = LaTeXFixer()
        self.render_engine = RenderEngine(config)
        self.shorthand_store = ShorthandStore(config)
        self.backend = BackendManager(config)
        # Agent Memory — per-session conversation context
        self.memory = ConversationMemory(max_turns=6)

    def _render(self, latex: str, render_mode: RenderMode | None) -> RenderResult:
        """Render using the request's mode override if one was supplied."""
        return self.render_engine.render(latex, mode_override=render_mode)

    def route(self, tab: Tab, content: str | bytes) -> Route:
        if tab == Tab.OCR:
            return Route.OCR
        if tab == Tab.SHORTHAND:
            return Route.SHORTHAND
        if tab == Tab.COMPLETION:
            return Route.COMPLETION
        # NL tab — auto-detect
        if isinstance(content, str):
            stripped = content.strip()
            if self.shorthand_store.has(stripped):
                return Route.SHORTHAND
            if self._is_partial_latex(stripped):
                return Route.COMPLETION
            return Route.NL2LATEX
        if isinstance(content, bytes):
            return Route.OCR
        return Route.NL2LATEX

    async def process_text(
        self,
        text: str,
        *,
        route_override: Route | None = None,
        intent_override: str | None = None,
        context: str = "",
        render_mode: RenderMode | None = None,
    ) -> ConvertResult:
        """Main entry point for text input (NL tab).

        Args:
            text: User input text.
            route_override: If set, force this route instead of auto-detecting.
            intent_override: If set, force this intent instead of auto-classifying.
            context: Extra context string (e.g. prior conversation) for the model.
            render_mode: Per-request render mode override.
        """
        start = time.monotonic()

        route = route_override or self.route(Tab.NL, text)
        text = text.strip()

        if route == Route.SHORTHAND:
            return await self._process_shorthand(text, start, render_mode=render_mode)

        if route == Route.COMPLETION:
            return await self._process_completion(
                text,
                start,
                context=context,
                render_mode=render_mode,
            )

        # NL→LaTeX
        return await self._process_nl2latex(
            text,
            start,
            intent_override=intent_override,
            context=context,
            render_mode=render_mode,
        )

    async def process_image(
        self,
        image: bytes,
        *,
        render_mode: RenderMode | None = None,
    ) -> ConvertResult:
        """Main entry point for image input (OCR tab)."""
        start = time.monotonic()

        latex, model_tokens = await self.create_ocr_candidate(image)

        final_latex, valid_result, tokens = self._validate_and_fix(
            latex,
            tokens_used=model_tokens,
        )
        render = self._render(final_latex, render_mode)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=final_latex,
            render=render,
            valid=valid_result.valid,
            source=Source.FIXED if final_latex != latex else Source.MODEL,
            intent="ocr",
            confidence=0.8,
            latency_ms=latency,
            tokens_used=tokens,
            fix_log=[] if valid_result.valid else ["auto-fixed"],
        )

    async def create_ocr_candidate(self, image: bytes) -> tuple[str, int]:
        """Use MiniCPM-V 4.6 only to propose the OCR candidate."""
        await self.backend.ensure_vision_ready()

        from texada.core.ocr import OCRPipeline

        ocr = OCRPipeline(self.model, self.config)
        latex = await ocr.process(image)
        return latex, self._consume_model_tokens()

    async def create_completion_candidate(
        self,
        text: str,
        *,
        context: str = "",
    ) -> tuple[str, int]:
        """Propose a completion before the shared Agent Runtime reviews it."""
        prompt = f"{context}\n{text}" if context else text
        ruled = self.model.rule_complete(text)
        if ruled:
            return self.operator_guard.normalize_candidate(ruled), 0

        normalized = self.operator_guard.normalize_candidate(text)
        deterministic, validation, _ = self._validate_and_fix(normalized)
        incomplete_tail = bool(re.search(r"[=+\-*/^_]\s*$", deterministic))
        if validation.valid and not incomplete_tail:
            return deterministic, 0

        await self.backend.ensure_ready()
        latex = await self.model.complete_latex(prompt)
        return latex, self._consume_model_tokens()

    # ── Private pipeline implementations ──

    async def _process_nl2latex(
        self, text: str, start: float,
        *,
        intent_override: str | None = None,
        context: str = "",
        render_mode: RenderMode | None = None,
    ) -> ConvertResult:
        if intent_override:
            intent_result = IntentResult(intent=intent_override, confidence=0.95)
        else:
            intent_result = self.intent_classifier.classify(text)
        preprocessed = self.symbol_engine.pre_translate(text)
        if context:
            preprocessed = f"[上下文: {context}]\n{preprocessed}"

        await self.backend.ensure_ready()

        # Pure chat inference — no tool calling
        latex = await self.model.generate_latex(
            preprocessed,
            intent_result.intent,
        )
        model_tokens = self._consume_model_tokens()

        # Operator-drift guard: if the small model downgraded or dropped the
        # operator the symbol engine pre-translated, retry once with the
        # required operators pinned in the prompt. Catches the "answered the
        # wrong question" failure mode (e.g. input \iint → output \int).
        if self._check_operator_drift(preprocessed, latex):
            forced = self._forced_operators(preprocessed)
            retried = await self.model.generate_latex(
                preprocessed,
                intent_result.intent,
                force_operators=forced,
            )
            model_tokens += self._consume_model_tokens()
            # Only adopt the retry if it actually still contains the forced
            # operators; otherwise keep the first answer for the validator to
            # flag rather than silently swap in another wrong answer.
            if retried and not self._check_operator_drift(preprocessed, retried):
                latex = retried

        # Store turn in Agent Memory
        self.memory.add(ConversationTurn(role="user", content=text))
        self.memory.add(ConversationTurn(role="assistant", content=latex))

        final_latex, valid_result, tokens = self._validate_and_fix(
            latex,
            tokens_used=model_tokens,
        )
        was_fixed = final_latex != latex
        source = Source.FIXED if was_fixed else Source.MODEL

        render = self._render(final_latex, render_mode)
        latency = (time.monotonic() - start) * 1000

        fix_log = [] if valid_result.valid else ["auto-fixed"]

        return ConvertResult(
            latex=final_latex,
            render=render,
            valid=valid_result.valid,
            source=source,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            latency_ms=latency,
            tokens_used=tokens,
            fix_log=fix_log,
        )

    async def _process_shorthand(
        self,
        text: str,
        start: float,
        *,
        render_mode: RenderMode | None = None,
    ) -> ConvertResult:
        result = self.shorthand_store.lookup(text)
        if result is None:
            return await self._process_nl2latex(text, start, render_mode=render_mode)

        final_latex, validation, tokens = self._validate_and_fix(result)
        render = self._render(final_latex, render_mode)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=final_latex,
            render=render,
            valid=validation.valid,
            source=Source.SHORTHAND if final_latex == result else Source.FIXED,
            intent="shorthand",
            confidence=1.0 if validation.valid else 0.0,
            latency_ms=latency,
            tokens_used=tokens,
        )

    async def _process_completion(
        self,
        text: str,
        start: float,
        *,
        context: str = "",
        render_mode: RenderMode | None = None,
    ) -> ConvertResult:
        latex, model_tokens = await self.create_completion_candidate(
            text,
            context=context,
        )

        final_latex, valid_result, tokens = self._validate_and_fix(
            latex,
            tokens_used=model_tokens,
        )
        render = self._render(final_latex, render_mode)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=final_latex,
            render=render,
            valid=valid_result.valid,
            source=Source.FIXED if final_latex != latex else Source.MODEL,
            intent="completion",
            confidence=0.7,
            latency_ms=latency,
            tokens_used=tokens,
        )

    def _validate_and_fix(
        self,
        latex: str,
        *,
        tokens_used: int = 0,
    ) -> tuple[str, ValidationResult, int]:
        """Validate and auto-fix if possible.

        Returns (final_latex, validation_result, tokens_used).
        final_latex is the fixed version when auto-fix succeeds.
        """
        result = self.validator.validate(latex)
        if result.valid:
            return latex, result, tokens_used
        # Try auto-fix
        fix = self.fixer.fix(latex, result.errors)
        if fix.fixed:
            re_validated = self.validator.validate(fix.latex)
            if re_validated.valid:
                return fix.latex, re_validated, tokens_used
        return latex, result, tokens_used

    def _consume_model_tokens(self) -> int:
        consume = getattr(self.model, "consume_tokens_used", None)
        if not callable(consume):
            return 0
        return int(consume() or 0)

    # Compatibility wrappers keep the original router test and extension seam
    # while sharing one implementation with the Agent Runtime.
    _INTEGRAL_LADDER = OperatorDriftGuard.INTEGRAL_LADDER
    _STANDALONE_OPS = OperatorDriftGuard.STANDALONE_OPS

    def _integral_rank(self, text: str) -> int:
        return self.operator_guard.integral_rank(text)

    def _check_operator_drift(self, preprocessed: str, model_output: str) -> bool:
        return self.operator_guard.check(preprocessed, model_output)

    def _forced_operators(self, preprocessed: str) -> list[str]:
        return self.operator_guard.forced_operators(preprocessed)

    def _is_partial_latex(self, text: str) -> bool:
        """Detect if text is an incomplete LaTeX fragment.

        Uses a pattern-based check: looks for \\command patterns (backslash
        followed by alphabetic characters) to distinguish LaTeX from plain
        arithmetic like "a+b=c".
        """
        if text.startswith("$"):
            return False
        # Must contain at least one LaTeX command (\frac, \int, \sum, etc.)
        return bool(re.search(r"\\[a-zA-Z]+", text))
