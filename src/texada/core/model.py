"""Gemma 4 E4B model wrapper — Ollama API calls."""
from __future__ import annotations

import asyncio
import re

import ollama

from texada.config import TeXadaConfig
from texada.core.prompts import (
    SYSTEM_PROMPT, COMPLETION_PROMPT, OCR_SYSTEM_PROMPT,
    FEW_SHOT_BY_INTENT,
)


class Gemma4E4B:
    """Wraps Ollama chat calls for Gemma 4 E4B."""

    def __init__(self, config: TeXadaConfig):
        self.client = ollama.Client(host=config.ollama_host)
        self.model = config.model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    async def generate_latex(self, preprocessed: str, intent: str) -> str:
        """NL→LaTeX inference."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
            {"role": "user", "content": preprocessed},
        ]
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=messages,
            options={"temperature": self.temperature, "num_predict": self.max_tokens},
        )
        return self._extract_latex(response.message.content)

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

    def _build_few_shot(self, intent: str) -> list[dict]:
        """Select intent-specific few-shot examples."""
        examples = FEW_SHOT_BY_INTENT.get(intent, FEW_SHOT_BY_INTENT["generic"])
        # Take first 3 to stay within context budget
        return [
            {"role": "user", "content": ex[0]},
            {"role": "model", "content": ex[1]},
        for ex in examples[:3]
        ]

    def _extract_latex(self, raw: str) -> str:
        """Strip $ delimiters and explanatory text from model output."""
        # Remove $$...$$ wrappers
        match = re.search(r'\$\$(.+?)\$\$', raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Remove $...$ wrappers
        match = re.search(r'\$(.+?)\$', raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        # If no delimiters, take the whole output (model sometimes forgets)
        lines = raw.strip().splitlines()
        # Return the last non-empty line (model may add commentary before)
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                return stripped
        return raw.strip()