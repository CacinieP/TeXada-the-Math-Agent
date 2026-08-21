"""TeX tool implementations and the runtime tool router."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from texada.config import TeXadaConfig
from texada.core.repair import DeterministicRepairService
from texada.core.validator import LaTeXValidator
from texada.render.engine import RenderEngine
from texada.semantic import SemanticDiffer, SemanticParser
from texada.semantic.model import SemanticDepthError
from texada.types import RenderMode

# Tools are CPU-bound and synchronous internally; each one runs on a worker
# thread with this wall-clock budget so one pathological input (e.g. a huge
# structural diff) cannot pin the whole service.
DEFAULT_TOOL_TIMEOUT_SECONDS = 10.0

ToolHandler = Callable[..., dict[str, Any]]
MAX_TEX_LENGTH = 4000


@dataclass
class ToolObservation:
    """A serializable observation returned to MiniCPM after a tool call."""

    name: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    # "model" marks malformed usage the model can correct (unknown tool,
    # invalid arguments); "tool" marks the tool itself failing (timeout,
    # structural limits, internal error). Drives the runtime's error-breaker
    # stop reason so run logs distinguish a confused planner from an unhealthy
    # tool layer.
    error_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.name,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 3),
            "error_class": self.error_class,
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class TeXToolset:
    """Single-purpose tools forming TeXada's professional math layer."""

    DEFINITIONS = (
        ToolDefinition(
            name="parse_tex",
            description=(
                "Parse LaTeX into a semantic math-unit tree. Use before reasoning "
                "about fractions, roots, integrals, limits, sums, or scripts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "LaTeX to parse"},
                },
                "required": ["latex"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="compile_tex",
            description=(
                "Validate and locally compile-check LaTeX. Returns diagnostics and "
                "the parsed semantic document."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "LaTeX to compile-check"},
                },
                "required": ["latex"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="repair_tex",
            description=(
                "Repair common LaTeX syntax errors with deterministic local rules, "
                "then revalidate the result. This tool does not invoke a model."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "Invalid LaTeX"},
                },
                "required": ["latex"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="semantic_diff",
            description=("Compare two formulas by mathematical units rather than character diff."),
            parameters={
                "type": "object",
                "properties": {
                    "before": {"type": "string", "description": "Original LaTeX"},
                    "after": {"type": "string", "description": "Updated LaTeX"},
                },
                "required": ["before", "after"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="render_math",
            description="Render valid LaTeX as KaTeX HTML or highlighted LaTeX.",
            parameters={
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "LaTeX to render"},
                    "mode": {
                        "type": "string",
                        "enum": ["katex", "latex"],
                        "default": "katex",
                    },
                },
                "required": ["latex"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="export",
            description="Export a formula as bare LaTeX, inline math, display math, or Markdown.",
            parameters={
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "LaTeX to export"},
                    "format": {
                        "type": "string",
                        "enum": ["latex", "inline", "display", "markdown"],
                        "default": "latex",
                    },
                },
                "required": ["latex"],
                "additionalProperties": False,
            },
        ),
    )

    def __init__(
        self,
        config: TeXadaConfig,
        *,
        repair_service: DeterministicRepairService | None = None,
    ):
        self.parser = SemanticParser()
        self.differ = SemanticDiffer(self.parser)
        self.validator = LaTeXValidator()
        self.renderer = RenderEngine(config)
        self.repair_service = repair_service or DeterministicRepairService()

    def parse_tex(self, latex: str) -> dict[str, Any]:
        latex = self._tex(latex)
        document = self.parser.parse(latex)
        return {"semantic_document": document.to_dict()}

    def compile_tex(self, latex: str) -> dict[str, Any]:
        latex = self._tex(latex)
        validation = self.validator.validate(latex)
        document = self.parser.parse(latex)
        return {
            "latex": latex,
            "valid": validation.valid,
            "diagnostics": [
                {
                    "type": item.type,
                    "detail": item.detail,
                    "error": item.error,
                }
                for item in validation.errors
            ],
            "semantic_document": document.to_dict(),
        }

    def repair_tex(self, latex: str) -> dict[str, Any]:
        latex = self._tex(latex)
        result = self.repair_service.repair(latex)
        output = result.to_dict()
        output["semantic_document"] = self.parser.parse(result.latex).to_dict()
        return output

    def semantic_diff(self, before: str, after: str) -> dict[str, Any]:
        before = self._tex(before, label="before")
        after = self._tex(after, label="after")
        result = self.differ.diff(before, after)
        output = result.to_dict(include_documents=True)
        output["semantic_document"] = result.after.to_dict() if result.after else None
        return output

    def render_math(self, latex: str, mode: str = "katex") -> dict[str, Any]:
        latex = self._tex(latex)
        validation = self.validator.validate(latex)
        if not validation.valid:
            diagnostics = "; ".join(
                item.detail or item.error or item.type
                for item in validation.errors
            )
            raise ValueError(
                "render_math requires validated LaTeX"
                + (f": {diagnostics}" if diagnostics else "")
            )
        try:
            render_mode = RenderMode(mode)
        except ValueError as exc:
            raise ValueError("mode must be 'katex' or 'latex'") from exc
        result = self.renderer.render(latex, mode_override=render_mode)
        return {
            "latex": latex,
            "mode": result.mode.value,
            "katex_html": result.katex_html,
            "latex_highlighted": result.latex_highlighted,
            "copy_text": result.copy_text,
            "semantic_document": self.parser.parse(latex).to_dict(),
        }

    def export(self, latex: str, format: str = "latex") -> dict[str, Any]:
        latex = self._tex(latex)
        formats = {
            "latex": latex,
            "inline": f"\\({latex}\\)",
            "display": f"\\[{latex}\\]",
            "markdown": f"$$\n{latex}\n$$",
        }
        if format not in formats:
            raise ValueError("format must be latex, inline, display, or markdown")
        return {
            "latex": latex,
            "format": format,
            "content": formats[format],
            "semantic_document": self.parser.parse(latex).to_dict(),
        }

    @staticmethod
    def _tex(value: str, *, label: str = "latex") -> str:
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a string")
        value = value.strip()
        if not value:
            raise ValueError(f"{label} must not be empty")
        if len(value) > MAX_TEX_LENGTH:
            raise ValueError(f"{label} exceeds {MAX_TEX_LENGTH} characters")
        return value


class ToolRouter:
    """Validate a requested tool name and turn execution into an observation."""

    def __init__(
        self,
        toolset: TeXToolset,
        *,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    ):
        self.toolset = toolset
        self.timeout_seconds = timeout_seconds
        self._handlers: dict[str, ToolHandler] = {
            definition.name: getattr(toolset, definition.name) for definition in toolset.DEFINITIONS
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [definition.to_openai() for definition in self.toolset.DEFINITIONS]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolObservation:
        start = time.monotonic()
        if name not in self._handlers:
            return ToolObservation(
                name=name,
                ok=False,
                error=f"Unknown tool '{name}'. Available: {', '.join(self.names)}",
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="model",
            )
        if not isinstance(arguments, dict):
            return ToolObservation(
                name=name,
                ok=False,
                error="Tool arguments must be a JSON object",
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="model",
            )
        try:
            # Tools are synchronous and CPU-bound; run them on a worker thread
            # so a slow tool cannot block the event loop, and enforce a
            # wall-clock budget so one pathological input cannot pin the
            # service. Note: a timed-out worker thread keeps running until it
            # finishes — the timeout bounds the request, not the thread.
            output = await asyncio.wait_for(
                asyncio.to_thread(self._handlers[name], **arguments),
                timeout=self.timeout_seconds,
            )
            return ToolObservation(
                name=name,
                ok=True,
                output=output,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except TimeoutError:
            return ToolObservation(
                name=name,
                ok=False,
                error=(
                    f"Tool '{name}' timed out after "
                    f"{self.timeout_seconds:g}s"
                ),
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="tool",
            )
        except SemanticDepthError as exc:
            return ToolObservation(
                name=name,
                ok=False,
                error=f"Tool '{name}' exceeded structural limits: {exc}",
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="tool",
            )
        except RecursionError:
            return ToolObservation(
                name=name,
                ok=False,
                error=f"Tool '{name}' exceeded recursion depth",
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="tool",
            )
        except TypeError as exc:
            return ToolObservation(
                name=name,
                ok=False,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="model",
            )
        except ValueError as exc:
            return ToolObservation(
                name=name,
                ok=False,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="model",
            )
        except RuntimeError as exc:
            return ToolObservation(
                name=name,
                ok=False,
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
                error_class="tool",
            )
