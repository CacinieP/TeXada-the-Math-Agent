"""Gemma 4 E4B model wrapper — Ollama API calls with Native Function Calling."""
from __future__ import annotations

import asyncio
import json
import re

import ollama

from texada.config import TeXadaConfig
from texada.core.prompts import (
    SYSTEM_PROMPT, COMPLETION_PROMPT, OCR_SYSTEM_PROMPT,
    FEW_SHOT_BY_INTENT,
)
from texada.types import ToolCall, ToolResult


# ── Native Function Calling tool schemas ──
LATEX_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "validate_latex",
            "description": "Validate generated LaTeX syntax. Returns errors if invalid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latex": {
                        "type": "string",
                        "description": "The LaTeX formula to validate",
                    },
                },
                "required": ["latex"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_symbol",
            "description": "Look up the correct LaTeX command for a Chinese mathematical term or symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The Chinese term or symbol name to look up",
                    },
                },
                "required": ["term"],
            },
        },
    },
]


class Gemma4E4B:
    """Wraps Ollama chat calls for Gemma 4 E4B with Native Function Calling."""

    def __init__(self, config: TeXadaConfig):
        self.client = ollama.Client(host=config.ollama_host)
        self.model = config.model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    # ── Public inference methods ──

    async def generate_latex(
        self,
        preprocessed: str,
        intent: str,
        memory_messages: list[dict] | None = None,
        tool_handlers: dict | None = None,
    ) -> tuple[str, list[ToolCall], list[ToolResult]]:
        """NL→LaTeX inference with optional Tool Calling loop.

        Returns (latex, tool_calls_executed, tool_results).
        """
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
        ]
        if memory_messages:
            messages.extend(memory_messages)
        messages.append({"role": "user", "content": preprocessed})

        all_tool_calls: list[ToolCall] = []
        all_tool_results: list[ToolResult] = []

        # First call with tools enabled
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            tools=LATEX_TOOLS,
            options={"temperature": self.temperature, "num_predict": self.max_tokens},
        )

        # Tool Calling loop (max 2 iterations to keep latency low)
        for _ in range(2):
            msg = response.message
            if not msg.tool_calls:
                break

            # Parse and execute all tool calls, then append ONE assistant message
            ollama_tool_calls: list[dict] = []
            tool_messages: list[dict] = []
            for tc in msg.tool_calls:
                # Bug 4 fix: arguments may already be a dict
                raw_args = tc.function.arguments
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

                tool_call = ToolCall(
                    id=getattr(tc, "id", ""),
                    name=tc.function.name,
                    arguments=args,
                )
                all_tool_calls.append(tool_call)

                # Execute tool if handler provided
                result_text = ""
                if tool_handlers and tool_call.name in tool_handlers:
                    result_text = tool_handlers[tool_call.name](**tool_call.arguments)
                else:
                    result_text = f"Error: no handler for {tool_call.name}"

                tool_result = ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    output=result_text,
                )
                all_tool_results.append(tool_result)

                # Collect tool call for single assistant message
                ollama_tool_calls.append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

                # Collect tool result (appended AFTER assistant message)
                tool_messages.append({
                    "role": "tool",
                    "content": result_text,
                    "name": tool_call.name,
                })

            # Bug 3 fix: ONE assistant message with ALL tool calls, BEFORE tool results
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": ollama_tool_calls,
            })
            # Then append all tool result messages
            messages.extend(tool_messages)

            # Re-run model with tool results
            response = await asyncio.to_thread(
                self.client.chat,
                model=self.model,
                messages=messages,
                tools=LATEX_TOOLS,
                options={"temperature": self.temperature, "num_predict": self.max_tokens},
            )

        latex = self._extract_latex(response.message.content)
        return latex, all_tool_calls, all_tool_results

    async def complete_latex(self, partial: str) -> str:
        """LaTeX completion inference."""
        messages = [
            {"role": "system", "content": COMPLETION_PROMPT},
            {"role": "user", "content": partial},
        ]
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={"temperature": 0.05, "num_predict": 128},
        )
        return self._extract_latex(response.message.content)

    async def ocr_latex(self, image: bytes) -> str:
        """OCR inference — multimodal input."""
        messages = [
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {"role": "user", "content": "识别图片中的数学公式", "images": [image]},
        ]
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={"temperature": 0.05, "num_predict": 256},
        )
        return self._extract_latex(response.message.content)

    # ── Helpers ──

    def _build_few_shot(self, intent: str) -> list[dict]:
        """Select intent-specific few-shot examples."""
        examples = FEW_SHOT_BY_INTENT.get(intent, FEW_SHOT_BY_INTENT["generic"])
        return [
            msg
            for ex in examples[:3]
            for msg in (
                {"role": "user", "content": ex[0]},
                {"role": "assistant", "content": ex[1]},
            )
        ]

    def _extract_latex(self, raw: str | None) -> str:
        """Strip $ delimiters and explanatory text from model output."""
        if not raw:
            return ""
        match = re.search(r'\$\$(.+?)\$\$', raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r'\$(.+?)\$', raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        lines = raw.strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                return stripped
        return raw.strip()