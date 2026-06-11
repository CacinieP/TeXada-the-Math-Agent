"""MiniCPM model wrapper — llama.cpp OpenAI-compatible API."""
from __future__ import annotations

import asyncio
import base64
import re

from openai import OpenAI

from texada.config import TeXadaConfig
from texada.core.prompts import (
    SYSTEM_PROMPT, COMPLETION_PROMPT, OCR_SYSTEM_PROMPT,
    FEW_SHOT_BY_INTENT,
)


class MiniCPMModel:
    """Wraps llama.cpp OpenAI-compatible chat calls for MiniCPM models."""

    def __init__(self, config: TeXadaConfig):
        self.client = OpenAI(
            base_url=f"{config.llama_host}/v1",
            api_key="sk-no-key",
        )
        self.model = config.model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        # Vision client for OCR (separate llama.cpp instance)
        self._vision_client = OpenAI(
            base_url=f"{config.llama_vision_host}/v1",
            api_key="sk-no-key",
        )
        self._vision_model = config.vision_model_name

    # ── Public inference methods ──

    async def generate_latex(
        self,
        preprocessed: str,
        intent: str,
        memory_messages: list[dict] | None = None,
    ) -> str:
        """NL→LaTeX inference — pure chat, no tool calling.

        Returns the extracted LaTeX string.
        """
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
        ]
        if memory_messages:
            messages.extend(memory_messages)
        messages.append({"role": "user", "content": preprocessed})

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        raw = response.choices[0].message.content if response.choices else ""
        return self._extract_latex(raw)

    async def complete_latex(self, partial: str) -> str:
        """LaTeX completion inference."""
        messages = [
            {"role": "system", "content": COMPLETION_PROMPT},
            {"role": "user", "content": partial},
        ]
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=messages,
            temperature=0.05,
            max_tokens=128,
        )
        raw = response.choices[0].message.content if response.choices else ""
        return self._extract_latex(raw)

    async def ocr_latex(self, image: bytes) -> str:
        """OCR inference — multimodal input via vision model."""
        b64_image = base64.b64encode(image).decode("utf-8")
        messages = [
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别图片中的数学公式"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                ],
            },
        ]
        response = await asyncio.to_thread(
            self._vision_client.chat.completions.create,
            model=self._vision_model,
            messages=messages,
            temperature=0.05,
            max_tokens=256,
        )
        raw = response.choices[0].message.content if response.choices else ""
        return self._extract_latex(raw)

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
