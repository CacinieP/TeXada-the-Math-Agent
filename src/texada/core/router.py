"""Input Router — unified entry point, dispatches to the correct pipeline."""
from __future__ import annotations

import asyncio

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
    ConvertResult, Route, Tab, Source, RenderMode, RenderResult,
)


class InputRouter:
    """Routes user input to the correct pipeline based on type and content."""

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

    async def process_text(self, text: str) -> ConvertResult:
        """Main entry point for text input (NL tab)."""
        import time
        start = time.monotonic()

        route = self.route(Tab.NL, text)
        text = text.strip()

        if route == Route.SHORTHAND:
            return await self._process_shorthand(text, start)

        if route == Route.COMPLETION:
            return await self._process_completion(text, start)

        # NL→LaTeX
        return await self._process_nl2latex(text, start)

    async def process_image(self, image: bytes) -> ConvertResult:
        """Main entry point for image input (OCR tab)."""
        import time
        start = time.monotonic()

        await self.ollama_manager.ensure_ready()

        from texada.core.ocr import OCRPipeline
        ocr = OCRPipeline(self.model, self.config)
        latex = await ocr.process(image)

        valid_result, tokens = self._validate_and_fix(latex)
        render = self.render_engine.render(valid_result.latex if not valid_result.valid else latex)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=latex,
            render=render,
            valid=valid_result.valid,
            source=Source.MODEL,
            intent="ocr",
            confidence=0.8,
            latency_ms=latency,
            tokens_used=tokens,
            fix_log=[] if valid_result.valid else ["auto-fixed"],
        )

    # ── Private pipeline implementations ──

    async def _process_nl2latex(self, text: str, start: float) -> ConvertResult:
        intent_result = self.intent_classifier.classify(text)
        preprocessed = self.symbol_engine.pre_translate(text)

        await self.ollama_manager.ensure_ready()
        latex = await self.model.generate_latex(
            preprocessed, intent_result.intent
        )

        valid_result, tokens = self._validate_and_fix(latex)
        source = Source.FIXED if valid_result.errors else Source.MODEL

        render = self.render_engine.render(latex)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=latex,
            render=render,
            valid=valid_result.valid,
            source=source,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            latency_ms=latency,
            tokens_used=tokens,
            fix_log=[] if valid_result.valid else ["auto-fixed"],
        )

    async def _process_shorthand(self, text: str, start: float) -> ConvertResult:
        import time
        result = self.shorthand_store.lookup(text)
        if result is None:
            return await self._process_nl2latex(text, start)

        render = self.render_engine.render(result)
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

    async def _process_completion(self, text: str, start: float) -> ConvertResult:
        import time
        await self.ollama_manager.ensure_ready()
        latex = await self.model.complete_latex(text)

        valid_result, tokens = self._validate_and_fix(latex)
        render = self.render_engine.render(latex)
        latency = (time.monotonic() - start) * 1000

        return ConvertResult(
            latex=latex,
            render=render,
            valid=valid_result.valid,
            source=Source.MODEL,
            intent="completion",
            confidence=0.7,
            latency_ms=latency,
            tokens_used=tokens,
        )

    def _validate_and_fix(self, latex: str) -> tuple[LaTeXValidator, int]:
        """Validate and auto-fix if possible. Returns (result, tokens_used)."""
        result = self.validator.validate(latex)
        if result.valid:
            return result, 0
        # Try auto-fix
        fix = self.fixer.fix(latex, result.errors)
        if fix.fixed:
            re_validated = self.validator.validate(fix.latex)
            if re_validated.valid:
                return re_validated, 0
        return result, 0

    def _is_partial_latex(self, text: str) -> bool:
        """Detect if text is an incomplete LaTeX fragment."""
        latex_chars = set(r"\{}_^=+")
        latex_count = sum(1 for c in text if c in latex_chars)
        return latex_count > len(text) * 0.3 and not text.startswith("$")