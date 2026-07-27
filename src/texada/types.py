"""TeXada types — shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Tab(StrEnum):
    NL = "nl"
    OCR = "ocr"
    COMPLETION = "completion"
    SHORTHAND = "shorthand"
    HISTORY = "history"
    SETTINGS = "settings"


class Route(StrEnum):
    NL2LATEX = "nl2latex"
    OCR = "ocr"
    COMPLETION = "completion"
    SHORTHAND = "shorthand"


class RenderMode(StrEnum):
    KATEX = "katex"
    LATEX = "latex"


class Source(StrEnum):
    MODEL = "model"
    SHORTHAND = "shorthand"
    TEMPLATE = "template"
    FIXED = "fixed"


@dataclass
class IntentResult:
    intent: str
    confidence: float


@dataclass
class CheckResult:
    ok: bool
    type: str = ""
    detail: str = ""
    error: str = ""


@dataclass
class ValidationResult:
    valid: bool
    errors: list[CheckResult] = field(default_factory=list)


@dataclass
class FixResult:
    latex: str
    fixed: bool
    log: list[str] = field(default_factory=list)


@dataclass
class RenderResult:
    latex: str
    katex_html: str | None = None
    latex_highlighted: str | None = None
    copy_text: str = ""
    mode: RenderMode = RenderMode.KATEX


@dataclass
class ConvertResult:
    """Full result of a conversion pipeline."""
    latex: str
    render: RenderResult
    valid: bool
    source: Source
    intent: str
    confidence: float
    latency_ms: float
    tokens_used: int = 0
    fix_log: list[str] = field(default_factory=list)


@dataclass
class HistoryEntry:
    id: int = 0
    run_id: str = ""
    input_text: str = ""
    input_type: str = ""
    latex: str = ""
    intent: str = ""
    source: str = ""
    render_mode: str = ""
    valid: bool = False
    latency_ms: float = 0.0
    tokens_used: int = 0
    starred: bool = False
    created_at: str = ""


@dataclass
class RunLogEntry:
    """One request-level execution record for diagnostics and reproducibility."""

    run_id: str = ""
    operation: str = ""
    input_type: str = ""
    input_text: str = ""
    input_bytes: int = 0
    input_mime: str = ""
    model_role: str = ""
    model_name: str = ""
    backend: str = ""
    status: str = "success"
    status_code: int = 200
    output_latex: str = ""
    intent: str = ""
    source: str = ""
    render_mode: str = ""
    valid: bool | None = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    stop_reason: str = ""
    tool_call_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    trace_available: bool = False
    error_message: str = ""
    created_at: str = ""


@dataclass
class ToolCall:
    """Native function call (legacy, kept for data compatibility)."""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result returned to the model after executing a tool (legacy)."""
    tool_call_id: str
    name: str
    output: str


@dataclass
class ConversationTurn:
    """Single turn stored in Agent Memory."""
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
