"""Adapters for MiniCPM5's native XML and OpenAI tool-call representations."""

from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlannerToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class PlannerTurn:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[PlannerToolCall] = field(default_factory=list)
    tokens_used: int = 0


class MiniCPMToolCallParser:
    """Normalize SGLang/OpenAI tool calls and raw MiniCPM5 XML.

    MiniCPM5's official chat template emits:
    ``<function name="..."><param name="...">...</param></function>``.
    SGLang can parse that into OpenAI ``tool_calls``. Ollama and other local
    servers may instead expose the XML in ``message.content``, so TeXada
    accepts both without inventing a second agent protocol.
    """

    _FUNCTION_BLOCK = re.compile(
        r"<function\s+name=[\"'][^\"']+[\"']\s*>.*?</function>",
        re.DOTALL,
    )
    _THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)

    def parse_message(self, message: Any, *, tokens_used: int = 0) -> PlannerTurn:
        content = getattr(message, "content", None) or ""
        reasoning = (
            getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None) or ""
        )
        native = getattr(message, "tool_calls", None) or []
        tool_calls = [self._native_call(item) for item in native]
        tool_calls = [item for item in tool_calls if item is not None]

        if not tool_calls:
            xml_calls, cleaned, xml_reasoning = self.parse_xml(content)
            tool_calls = xml_calls
            content = cleaned
            reasoning = reasoning or xml_reasoning

        return PlannerTurn(
            content=content.strip(),
            reasoning=reasoning.strip(),
            tool_calls=tool_calls,
            tokens_used=tokens_used,
        )

    def parse_xml(self, content: str) -> tuple[list[PlannerToolCall], str, str]:
        think_match = self._THINK_BLOCK.search(content)
        reasoning = think_match.group(1).strip() if think_match else ""
        visible = self._THINK_BLOCK.sub("", content)
        blocks = self._FUNCTION_BLOCK.findall(visible)
        calls: list[PlannerToolCall] = []
        for block in blocks:
            parsed = self._parse_function_block(block)
            if parsed:
                calls.append(parsed)
        cleaned = self._FUNCTION_BLOCK.sub("", visible).replace("<tool_sep>", "").strip()
        return calls, cleaned, reasoning

    def _native_call(self, item: Any) -> PlannerToolCall | None:
        function = getattr(item, "function", None)
        if function is None and isinstance(item, dict):
            function = item.get("function", item)
        if function is None:
            return None
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        if isinstance(function, dict):
            name = function.get("name", name)
            arguments = function.get("arguments", arguments)
        if not name:
            return None
        return PlannerToolCall(
            id=getattr(item, "id", None)
            or (item.get("id") if isinstance(item, dict) else None)
            or self._call_id(),
            name=str(name),
            arguments=self._arguments(arguments),
        )

    def _parse_function_block(self, block: str) -> PlannerToolCall | None:
        try:
            element = ET.fromstring(block)
            name = element.attrib.get("name", "")
            arguments = {
                child.attrib.get("name", ""): self._coerce(child.text or "")
                for child in element.findall("param")
                if child.attrib.get("name")
            }
            if name:
                return PlannerToolCall(
                    id=self._call_id(),
                    name=name,
                    arguments=arguments,
                )
        except ET.ParseError:
            pass

        name_match = re.search(r"<function\s+name=[\"']([^\"']+)[\"']", block)
        if not name_match:
            return None
        arguments: dict[str, Any] = {}
        for match in re.finditer(
            r"<param\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</param>",
            block,
            re.DOTALL,
        ):
            value = re.sub(r"^<!\[CDATA\[|\]\]>$", "", match.group(2).strip())
            arguments[match.group(1)] = self._coerce(value)
        return PlannerToolCall(
            id=self._call_id(),
            name=name_match.group(1),
            arguments=arguments,
        )

    def _arguments(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _coerce(value: str) -> Any:
        stripped = value.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped

    @staticmethod
    def _call_id() -> str:
        return f"call_{uuid.uuid4().hex[:20]}"
