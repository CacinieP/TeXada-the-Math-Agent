"""Model wrapper — OpenAI-compatible chat API."""
from __future__ import annotations

import asyncio
import base64
import re
from contextvars import ContextVar
from typing import Any

import httpx
from openai import APITimeoutError, BadRequestError, OpenAI

from texada.agent.protocol import MiniCPMToolCallParser, PlannerTurn
from texada.config import TeXadaConfig
from texada.core.prompts import (
    COMPLETION_PROMPT,
    FEW_SHOT_BY_INTENT,
    OCR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from texada.core.validator import LaTeXValidator

# Rule-based completions for high-frequency LaTeX fragments. Matched against
# the stripped input's tail (first match wins). MiniCPM5-1B is unreliable on
# these common patterns (it tends to emit empty braces), so rules take
# precedence and are instant; the model only handles fragments no rule
# recognises.
_RULE_COMPLETIONS: list[tuple[str, str]] = [
    (r"\\alp$", "ha"),
    (r"\\bet$", "a"),
    (r"\\gam$", "ma"),
    (r"\\del$", "ta"),
    (r"\\the$", "ta"),
    (r"\\lam$", "bda"),
    (r"\\sig$", "ma"),
    (r"\\ome$", "ga"),
    (r"\\part$", "ial"),
    (r"\\sum_\{i=1\}\^\{$", "n} x_i"),
    (r"\\sum_\{$", "i=1}^{n} x_i"),
    (r"\\sum$", "_{i=1}^{n} x_i"),
    (r"\\prod_\{$", "i=1}^{n} x_i"),
    (r"\\prod$", "_{i=1}^{n} x_i"),
    (r"\\frac\{$", r"\placeholder{}}{\placeholder{}}"),
    (r"\\sqrt\{$", r"\placeholder{}}"),
    (r"\\int$", "_{0}^{1} f(x)\\,dx"),
    (r"\\int_\{$", "0}^{1} f(x)\\,dx"),
    (r"\\lim$", "_{x \\to 0}"),
    (r"\\lim_\{$", "x \\to 0}"),
    (r"\\mathbb\{$", "R}"),
    (r"\\mathcal\{$", "L}"),
    (r"\^\{$", r"\placeholder{}}"),
    (r"_\{$", r"\placeholder{}}"),
    (r"\{$", r"\placeholder{}}"),
]
FORMULA_MAX_TOKENS = 768


class MiniCPMModel:
    """Wraps a local Ollama or custom OpenAI-compatible chat API."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._client: OpenAI | None = None
        self.model = config.active_model_name
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        # Vision (OCR) uses the same endpoint, with an optional separate model name.
        self._vision_model = config.active_vision_model_name
        self._tool_parser = MiniCPMToolCallParser()
        self._formula_validator = LaTeXValidator()
        # Request-local telemetry: one shared model instance may serve several
        # concurrent FastAPI tasks, so a plain instance integer would race.
        self._request_tokens: ContextVar[int] = ContextVar(
            f"texada_model_tokens_{id(self)}",
            default=0,
        )

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            base_url = self.config.active_base_url
            api_key = self.config.active_api_key
            if not base_url:
                raise RuntimeError("Inference endpoint is not configured")
            if not api_key:
                raise RuntimeError("Inference API key is not configured")
            timeout = httpx.Timeout(
                self.config.inference_timeout_seconds,
                connect=min(10.0, self.config.inference_timeout_seconds),
            )
            self._client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=self.config.inference_timeout_seconds,
                # The request-level timeout is an explicit product contract.
                # SDK retries would otherwise turn 45 seconds into ~135 seconds.
                max_retries=0,
                http_client=httpx.Client(
                    timeout=timeout,
                    trust_env=self.config.uses_openai_compatible,
                ),
            )
        return self._client

    def _completion_create(self, **kwargs):
        try:
            return self.client.chat.completions.create(**kwargs)
        except (APITimeoutError, httpx.TimeoutException) as exc:
            raise RuntimeError(
                f"模型请求超时（{self.config.inference_timeout_seconds:.0f}s），"
                "请检查 Ollama/endpoint 是否响应，或在配置中调高 inference_timeout_seconds。"
            ) from exc

    def _text_model_name(self) -> str:
        if not self.model:
            raise RuntimeError("Text model name is not configured")
        return self.model

    def _vision_model_name(self) -> str:
        if not self._vision_model:
            raise RuntimeError("Vision model name is not configured")
        return self._vision_model

    # ── Public inference methods ──

    async def plan(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> PlannerTurn:
        """Run one MiniCPM5 planner turn with its native tool definitions.

        SGLang returns normalized OpenAI ``tool_calls``. Some local runtimes
        leave MiniCPM5's official XML in ``content``; the parser accepts both.
        """
        kwargs = {
            "model": self._text_model_name(),
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            response = await asyncio.to_thread(self._completion_create, **kwargs)
        except BadRequestError:
            # Compatibility path for OpenAI-shaped endpoints that reject the
            # tools field. The runtime will still validate direct LaTeX output.
            kwargs.pop("tools")
            kwargs.pop("tool_choice")
            response = await asyncio.to_thread(self._completion_create, **kwargs)

        if not response.choices:
            return PlannerTurn()
        usage = getattr(response, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        return self._tool_parser.parse_message(
            response.choices[0].message,
            tokens_used=tokens,
        )

    async def generate_latex(
        self,
        preprocessed: str,
        intent: str,
        memory_messages: list[dict] | None = None,
        force_operators: list[str] | None = None,
    ) -> str:
        """NL→LaTeX inference — pure chat, no tool calling.

        Returns the extracted LaTeX string.

        ``force_operators``: operators (e.g. ``r"\\iint"``) that the output
        MUST contain. When provided, a missing operator triggers one
        constrained retry (in addition to the existing empty-output retry),
        so the small model can't silently downgrade the operator the symbol
        engine pre-translated into the prompt.
        """
        self._reset_tokens()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._build_few_shot(intent),
        ]
        if memory_messages:
            messages.extend(memory_messages)
        messages.append({"role": "user", "content": preprocessed})

        response = await asyncio.to_thread(
            self._completion_create,
            model=self._text_model_name(),
            messages=messages,
            temperature=self.temperature,
            max_tokens=min(self.max_tokens, FORMULA_MAX_TOKENS),
        )
        self._record_response_tokens(response)
        raw = response.choices[0].message.content if response.choices else ""
        latex = self._extract_latex(raw)

        # Reasoning models (e.g. MiniCPM5) often put the real answer in the
        # `reasoning` field and leave `content` empty (especially when max_tokens
        # is consumed by the chain-of-thought). Fall back to extracting from it.
        if not latex and response.choices:
            reasoning = getattr(response.choices[0].message, "reasoning", None)
            if reasoning:
                latex = self._extract_latex(reasoning)

        # Retry once when the answer is missing OR drifted (dropped a forced
        # operator). The stricter prompt pins the required operators so the
        # small model can't mimic an unrelated few-shot and downgrade them.
        missing = self._missing_operators(latex, force_operators)
        if not latex or missing:
            constraint = self._operator_constraint(missing or force_operators)
            try:
                retry = await asyncio.to_thread(
                    self._completion_create,
                    model=self._text_model_name(),
                    messages=[
                        {
                            "role": "system",
                            "content": SYSTEM_PROMPT
                            + "\n\n重要：只输出最终的 LaTeX 公式本身，"
                            "不要任何解释、自然语言或 markdown 代码块。"
                            + constraint,
                        },
                        *self._build_few_shot(intent),
                        {"role": "user", "content": preprocessed},
                    ],
                    temperature=0.1,
                    max_tokens=min(self.max_tokens, FORMULA_MAX_TOKENS),
                )
                self._record_response_tokens(retry)
                rraw = retry.choices[0].message.content if retry.choices else ""
                retry_latex = self._extract_latex(rraw)
                # Only adopt the retry if it actually fixed the problem;
                # otherwise keep the (possibly drifted) first answer and let
                # the validator flag it. Never regress to empty.
                if retry_latex and not self._missing_operators(retry_latex, force_operators):
                    latex = retry_latex
            except Exception:
                pass

        return latex

    async def complete_latex(self, partial: str) -> str:
        """LaTeX completion — rules first for common patterns, model otherwise.

        MiniCPM5-1B is unreliable at completing arbitrary fragments (it tends
        to emit empty braces), so high-frequency patterns are matched by rule
        first (accurate, zero latency); the model handles the rest.
        """
        self._reset_tokens()
        ruled = self.rule_complete(partial)
        if ruled:
            return ruled

        messages = [
            {"role": "system", "content": COMPLETION_PROMPT},
            {"role": "user", "content": partial},
        ]
        response = await asyncio.to_thread(
            self._completion_create,
            model=self._text_model_name(),
            messages=messages,
            temperature=0.05,
            max_tokens=min(self.max_tokens, FORMULA_MAX_TOKENS),
        )
        self._record_response_tokens(response)
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
        self._reset_tokens()
        b64_image = base64.b64encode(image).decode("utf-8")
        messages = [
            {"role": "system", "content": OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别图片中的数学公式"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ]
        kwargs = {
            "model": self._vision_model_name(),
            "messages": messages,
            "temperature": 0.05,
            "max_tokens": 512,
        }
        if self.config.uses_openai_compatible:
            kwargs["reasoning_effort"] = "low"
        response = await asyncio.to_thread(
            self._completion_create,
            **kwargs,
        )
        self._record_response_tokens(response)
        latex = self._response_latex(response)
        if latex:
            return latex

        # MiniCPM-V may consume its first answer on internal reasoning and
        # expose neither content nor a usable reasoning field. Retry once with
        # an explicit final-answer constraint; the Agent Runtime handles all
        # validation and deterministic repair after this candidate exists.
        retry_messages = [
            {
                "role": "system",
                "content": (
                    OCR_SYSTEM_PROMPT
                    + "\n\n硬性要求：必须在最终回答中输出可见的 LaTeX。"
                    "只提取图片中的单条主体公式，不要输出思考过程。"
                ),
            },
            messages[1],
        ]
        retry_kwargs = {
            **kwargs,
            "messages": retry_messages,
            "temperature": 0.0,
            "max_tokens": min(self.max_tokens, FORMULA_MAX_TOKENS),
        }
        retry = await asyncio.to_thread(
            self._completion_create,
            **retry_kwargs,
        )
        self._record_response_tokens(retry)
        latex = self._response_latex(retry)
        if latex:
            return latex
        raise RuntimeError(
            "OCR 视觉模型未返回可识别的公式，请裁剪到单个公式或换一张更清晰的图片。"
        )

    # ── Helpers ──

    def rule_complete(self, partial: str) -> str | None:
        """Complete a fragment by exact tail-match against common patterns."""
        s = partial.strip()
        for pattern, suffix in _RULE_COMPLETIONS:
            if re.search(pattern + r"\s*$", s):
                return s + suffix
        return None

    # Backwards-compatible private alias for tests and extensions.
    _rule_complete = rule_complete

    def consume_tokens_used(self) -> int:
        """Return and clear token usage for the current async request."""
        tokens = self._request_tokens.get()
        self._request_tokens.set(0)
        return tokens

    def _reset_tokens(self) -> None:
        self._request_tokens.set(0)

    def _record_response_tokens(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        self._request_tokens.set(self._request_tokens.get() + tokens)

    def _response_latex(self, response: Any) -> str:
        """Extract a formula from visible or reasoning response fields."""
        if not getattr(response, "choices", None):
            return ""
        message = response.choices[0].message
        for field in ("content", "reasoning", "reasoning_content"):
            latex = self._extract_latex(getattr(message, field, None))
            if latex:
                return latex
        return ""

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

    def _missing_operators(self, latex: str, ops: list[str] | None) -> list[str]:
        """Which required operators are absent from the model output."""
        if not ops:
            return []
        return [op for op in ops if op not in latex]

    def _operator_constraint(self, ops: list[str] | None) -> str:
        """Build a Chinese instruction pinning the required operators.

        e.g. for [r'\\iint', r'\\sum'] → a sentence telling the model the
        output must contain both, verbatim, with no downgrade.
        """
        if not ops:
            return ""
        joined = "、".join(ops)
        return (
            f"\n\n硬性要求：输出公式必须原样包含算符 {joined}，"
            "不得降级（例如把 \\iint 改成 \\int）或省略。"
        )

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
        result = result.strip()
        if result and not self._formula_validator.has_formula_content(result):
            return ""
        return result

    def extract_latex(self, raw: str | None) -> str:
        """Public final-answer extractor shared with the Agent Runtime."""
        return self._extract_latex(raw)
