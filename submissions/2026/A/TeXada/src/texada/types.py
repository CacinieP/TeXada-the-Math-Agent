"""TeXada types — shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tab(str, Enum):
    NL = "nl"
    OCR = "ocr"
    COMPLETION = "completion"
    SHORTHAND = "shorthand"
    HISTORY = "history"
    SETTINGS = "settings"


class Route(str, Enum):
    NL2LATEX = "nl2latex"
    OCR = "ocr"
    COMPLETION = "completion"
    SHORTHAND = "shorthand"


class RenderMode(str, Enum):
    KATEX = "katex"
    LATEX = "latex"


class Source(str, Enum):
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
    id: int
    input_text: str
    input_type: str
    latex: str
    intent: str
    source: str
    render_mode: str
    valid: bool
    latency_ms: float
    tokens_used: int
    starred: bool
    created_at: str


@dataclass
class ToolCall:
    """Native function call emitted by Gemma 4."""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result returned to the model after executing a tool."""
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