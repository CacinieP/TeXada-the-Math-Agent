"""MiniCPM model wrapper — Ollama OpenAI-compatible API."""
from __future__ import annotations

import asyncio
import base64
import re

import httpx
from openai import OpenAI

from texada.config import TeXadaConfig
from texada.core.prompts import (
    COMPLETION_PROMPT,
    FEW_SHOT_BY_INTENT,
    OCR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)

# Rule-based completions for high-frequency LaTeX fragments. Matched against
# the stripped input's tail (first match wins). MiniCPM5-1B is unreliable on
# these common patterns (it tends to emit empty braces), so rules take
# precedence and are instant; the model only handles fragments no rule
# recognises.
_RULE_COMPLETIONS: list[tuple[str, str]] = [
    (r"\\sum_\{i=1\}\^\{$", "n} x_i"),
    (r"\\sum_\{$", "i=1}^{n} x_i"),
    (r"\\sum$", "_{i=1}^{n} x_i"),
    (r"\\prod_\{$", "i=1}^{n} x_i"),
    (r"\\prod$", "_{i=1}^{n} x_i"),
    (r"\\frac\{$", "}{}"),
    (r"\\sqrt\{$", "}"),
    (r"\\int$", "_{0}^{1} f(x)\\,dx"),
    (r"\\int_\{$", "0}^{1} f(x)\\,dx"),
    (r"\\lim$", "_{x \\to 0}"),
    (r"\\lim_\{$", "x \\to 0}"),
    (r"\\mathbb\{$", "R}"),
    (r"\\mathcal\{$", "L}"),
    (r"\^\{$", "n}"),
    (r"_\{$", "}"),
    (r"\{$", "}"),
]


class MiniCPMModel:
    """Wraps Ollama's OpenAI-compatible chat API for MiniCPM models."""

    def __init__(self, config: TeXadaConfig):
        # Ollama exposes an OpenAI-compatible /v1 endpoint; text and vision
        # share the same daemon, distinguished by model tag.
        self.client = OpenAI(
            base_url=f"{config.ollama_host}/v1",
            api_key="ollama",  # Ollama ignores the key; SDK requires a non-empty value
            http_client=httpx.Client(trust_env=False),  # local Ollama: never use system proxy
        )
        self.model = config.model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        # Vision (OCR) uses the same daemon, just a different model tag.
        self._vision_client = self.client
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
        latex = self._extract_latex(raw)

        # Reasoning models (e.g. MiniCPM5) often put the real answer in the
        # `reasoning` field and leave `content` empty (especially when max_tokens
        # is consumed by the chain-of-thought). Fall back to extracting from it.
        if not latex and response.choices:
            reasoning = getattr(response.choices[0].message, "reasoning", None)
            if reasoning:
                latex = self._extract_latex(reasoning)

        # Error recovery: the model occasionally returns empty content on
        # NL→LaTeX. Retry once with a stricter prompt (formula only, no prose,
        # no markdown). Retry failure falls through; validator marks invalid.
        if not latex:
            try:
                retry = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": SYSTEM_PROMPT
                            + "\n\n重要：只输出最终的 LaTeX 公式本身，"
                            "不要任何解释、自然语言或 markdown 代码块。",
                        },
                        *self._build_few_shot(intent),
                        {"role": "user", "content": preprocessed},
                    ],
                    temperature=0.1,
                    max_tokens=self.max_tokens,
                )
                rraw = retry.choices[0].message.content if retry.choices else ""
                latex = self._extract_latex(rraw)
            except Exception:
                pass

        return latex

    async def complete_latex(self, partial: str) -> str:
        """LaTeX completion — rules first for common patterns, model otherwise.

        MiniCPM5-1B is unreliable at completing arbitrary fragments (it tends
        to emit empty braces), so high-frequency patterns are matched by rule
        first (accurate, zero latency); the model handles the rest.
        """
        ruled = self._rule_complete(partial)
        if ruled:
            return ruled

        messages = [
            {"role": "system", "content": COMPLETION_PROMPT},
            {"role": "user", "content": partial},
        ]
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=messages,
            temperature=0.05,
            max_tokens=self.max_tokens,
        )
        raw = response.choices[0].message.content if response.choices else ""
        latex = self._extract_latex(raw)
        # Reasoning models (e.g. MiniCPM5) may leave `content` empty and put the
        # answer in `reasoning`. Fall back to it before giving up.
        if not latex and response.choices:
            reasoning = getattr(response.choices[0].message, "reasoning", None)
            if reasoning:
                latex = self._extract_latex(reasoning)
        return latex

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

    def _rule_complete(self, partial: str) -> str | None:
        """Complete a fragment by exact tail-match against common patterns."""
        s = partial.strip()
        for pattern, suffix in _RULE_COMPLETIONS:
            if re.search(pattern + r"\s*$", s):
                return s + suffix
        return None

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
        """Strip markdown code fences, math delimiters, and explanatory text."""
        if not raw:
            return ""
        text = raw.strip()

        # 1. Markdown code fences: ```latex\n...\n``` (lang tag optional)
        fence = re.search(r'```(?:[a-zA-Z]*)?\s*(.*?)```', text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

        result = ""
        # 2. $$ ... $$ display math
        m = re.search(r'\$\$(.+?)\$\$', text, re.DOTALL)
        if m:
            result = m.group(1).strip()
        # 3. $ ... $ inline math
        elif (m := re.search(r'\$(.+?)\$', text, re.DOTALL)):
            result = m.group(1).strip()
        # 3b. \( ... \) inline and \[ ... \] display (LaTeX delimiters)
        elif (m := re.search(r'\\\((.+?)\\\)', text, re.DOTALL)):
            result = m.group(1).strip()
        elif (m := re.search(r'\\\[(.+?)\\\]', text, re.DOTALL)):
            result = m.group(1).strip()
        else:
            # 4. Fallback: last non-empty line, skipping fence markers and
            #    punctuation/ellipsis-only lines (reasoning trails often end with "…").
            for line in reversed(text.splitlines()):
                stripped = line.strip().strip('`').strip()
                if stripped and not re.match(r'^[.\。，…\s]+$', stripped):
                    result = stripped
                    break
            if not result:
                result = text.strip('`').strip()

        # 5. Strip any residual unclosed math delimiters around the result.
        result = re.sub(r'^(\$\$|\$|\\\[|\\\()\s*', '', result)
        result = re.sub(r'\s*(\\\]|\\\)|\$\$|\$)$', '', result)
        return result.strip()
