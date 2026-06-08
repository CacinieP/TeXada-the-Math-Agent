"""Input Router — unified entry point, dispatches to the correct pipeline.
Implements Agent Memory + Native Function Calling loop.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from texada.config import TeXadaConfig
from texada.core.intent import IntentClassifier
from texada.core.model import Gemma4E4B
from texada.core.ollama_manager import OllamaManager
from texada.core.symbols import SymbolEngine
from texada.core.validator import LaTeXValidator
from texada.core.fixer import LaTeXFixer
from texada.render.engine import RenderEngine
from texada.store.shorthand import ShorthandStore
from texada.types import (
    ConvertResult, IntentResult, Route, Tab, Source, RenderMode, RenderResult,
    ConversationTurn, ToolCall, ToolResult, ValidationResult,
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
        """Export as Ollama-compatible message list."""
        messages: list[dict] = []
        for turn in self.turns:
            msg: dict = {"role": turn.role, "content": turn.content}
            if turn.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in turn.tool_calls
                ]
            messages.append(msg)
            # Emit tool result messages for proper Ollama API context
            for tr in turn.tool_results:
                messages.append({
                    "role": "tool",
                    "content": tr.output,
                    "name": tr.name,
                })
        return messages

    def clear(self) -> None:
        self.turns.clear()


class InputRouter:
    """Routes user input to the correct pipeline based on type and content.
    Integrates Agent Memory and Native Function Calling (Tool Calling).
    """

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self.intent_classifier = IntentClassifier()
        self.symbol_engine = SymbolEngine()
        self.model = Gemma4E4B(config)
        self.validator = LaTeXValidator()
        self.fixer = LaTeXFixer()
        self.render_engine = RenderEngine(config)
        self.shorthand_store = ShorthandStore(config)
        self.ollama_manager = OllamaManager(config)
        # Agent Memory — per-session conversation context
        self.memory = ConversationMemory(max_turns=6)
        self._per_request_mode: RenderMode | None = None

    def _render(self, latex: str) -> RenderResult:
        """Render using per-request mode override if set, else default mode."""
        return self._render(latex, mode_override=self._per_request_mode)

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
            render_mode: Per-request render mode override (avoids mutating shared state).
        """
        start = time.monotonic()
        self._per_request_mode = render_mode  # Used by self._render()

        route = route_override or self.route(Tab.NL, text)
        text = text.strip()

        if route == Route.SHORTHAND:
            return await self._process_shorthand(text, start)

        if route == Route.COMPLETION:
            return await self._process_completion(text, start, context=context)

        # NL→LaTeX
        return await self._process_nl2latex(text, start, intent_override=intent_override, context=context)

    async def process_image(self, image: bytes, *, render_mode: RenderMode | None = None) -> ConvertResult:
        """Main entry point for image input (OCR tab)."""
        start = time.monotonic()
        self._per_request_mode = render_mode

        await self.ollama_manager.ensure_ready()

        from texada.core.ocr import OCRPipeline
        ocr = OCRPipeline(self.model, self.config)
        latex = await ocr.process(image)

        final_latex, valid_result, tokens = self._validate_and_fix(latex)
        render = self._render(final_latex)
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

    # ── Tool handlers for Native Function Calling ──

    def _tool_validate_latex(self, latex: str) -> str:
        result = self.validator.validate(latex)
        if result.valid:
            return "Valid LaTeX."
        errors = "; ".join(f"{e.type}: {e.detail}" for e in result.errors)
        return f"Invalid: {errors}"

    def _tool_lookup_symbol(self, term: str) -> str:
        translated = self.symbol_engine.translate(term)
        if translated:
            return f"'{term}' -> '{translated}'"
        return f"No exact match for '{term}'. Use standard LaTeX command."

    def _build_tool_handlers(self) -> dict:
        return {
            "validate_latex": self._tool_validate_latex,
            "lookup_symbol": self._tool_lookup_symbol,
        }

    # ── Private pipeline implementations ──

    async def _process_nl2latex(
        self, text: str, start: float,
        *, intent_override: str | None = None, context: str = "",
    ) -> ConvertResult:
        if intent_override:
            intent_result = IntentResult(intent=intent_override, confidence=0.95)
        else:
            intent_result = self.intent_classifier.classify(text)
        preprocessed = self.symbol_engine.pre_translate(text)
        if context:
            preprocessed = f"[上下文: {context}]\n{preprocessed}"

        await self.ollama_manager.ensure_ready()

        # Native Function Calling with Agent Memory
        latex, tool_calls, tool_results = await self.model.generate_latex(
            preprocessed,
            intent_result.intent,
            memory_messages=self.memory.to_messages(),
            tool_handlers=self._build_tool_handlers(),
        )

        # Store turn in Agent Memory
        self.memory.add(ConversationTurn(
            role="user", content=text,
        ))
        self.memory.add(ConversationTurn(
            role="assistant", content=latex,
            tool_calls=tool_calls,
            tool_results=tool_results,
        ))

        final_latex, valid_result, tokens = self._validate_and_fix(latex)
        was_fixed = final_latex != latex
        source = Source.FIXED if was_fixed else Source.MODEL

        # If model used validate_latex and found errors, mark as FIXED
        if any(tr.name == "validate_latex" and "Invalid" in tr.output for tr in tool_results):
            source = Source.FIXED

        render = self._render(final_latex)
        latency = (time.monotonic() - start) * 1000

        fix_log = [] if valid_result.valid else ["auto-fixed"]
        if tool_results:
            fix_log.append(f"tools_used: {[tr.name for tr in tool_results]}")

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

    async def _process_shorthand(self, text: str, start: float) -> ConvertResult:
        result = self.shorthand_store.lookup(text)
        if result is None:
            return await self._process_nl2latex(text, start)

        render = self._render(result)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=result,
            render=render,
            valid=True,
            source=Source.SHORTHAND,
            intent="shorthand",
            confidence=1.0,
            latency_ms=latency,
            tokens_used=0,
        )

    async def _process_completion(self, text: str, start: float, *, context: str = "") -> ConvertResult:
        await self.ollama_manager.ensure_ready()
        prompt = f"{context}\n{text}" if context else text
        latex = await self.model.complete_latex(prompt)

        final_latex, valid_result, tokens = self._validate_and_fix(latex)
        render = self._render(final_latex)
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

    def _validate_and_fix(self, latex: str) -> tuple[str, ValidationResult, int]:
        """Validate and auto-fix if possible.

        Returns (final_latex, validation_result, tokens_used).
        final_latex is the fixed version when auto-fix succeeds.
        """
        result = self.validator.validate(latex)
        if result.valid:
            return latex, result, 0
        # Try auto-fix
        fix = self.fixer.fix(latex, result.errors)
        if fix.fixed:
            re_validated = self.validator.validate(fix.latex)
            if re_validated.valid:
                return fix.latex, re_validated, 0
        return latex, result, 0

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
