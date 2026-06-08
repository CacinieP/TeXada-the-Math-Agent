"""
TeXada Agent — core pipeline.
Text → LaTeX using symbol dict + templates + Gemma 4 E4B fallback.
"""

from dataclasses import dataclass

import ollama

from symbol_dict import SYMBOL_TABLE, TEMPLATES, SHORTHANDS


MODEL = "gemma4:e4b"

SYSTEM_PROMPT = """\
You are a math formula converter. The user describes a math formula in natural language (Chinese or English).
You output ONLY valid LaTeX code. No explanation, no dollar signs, no markdown.

Rules:
- No $...$ or $$...$$ wrappers
- Use \\left \\right for auto-sizing delimiters when nesting
- Use \\, for thin spaces before dx, dy, dt etc.
- Use pmatrix for matrices
- Use cases for piecewise functions
- Use \\text{} for any Chinese text inside math

Examples:
Input: x的平方加y的平方等于r的平方
Output: x^{2} + y^{2} = r^{2}

Input: e的x次方从0到1的积分
Output: \\int_{0}^{1} e^{x} \\, dx

Input: 3x3单位矩阵
Output: \\begin{pmatrix} 1 & 0 & 0 \\\\ 0 & 1 & 0 \\\\ 0 & 0 & 1 \\end{pmatrix}

Input: f of x equals x squared when x greater than 0, equals negative x when x less than 0
Output: f(x) = \\begin{cases} x^{2} & x > 0 \\\\ -x & x \\leq 0 \\end{cases}
"""


@dataclass
class ConversionResult:
    latex: str
    source: str  # "template" | "llm"
    matched_template: str | None = None
    render_ok: bool = True
    render_error: str | None = None


class TeXadaAgent:
    """Pipeline: shorthand → template → symbol dict → LLM → validation."""

    def __init__(self, model: str = MODEL):
        self.model = model

    def convert(self, text: str) -> ConversionResult:
        # Phase 1: shorthand expansion
        expanded = self._expand_shorthands(text)

        # Phase 2: template match (exact or fuzzy)
        template_result = self._match_template(expanded)
        if template_result:
            return template_result

        # Phase 3: LLM conversion
        latex = self._llm_convert(expanded)
        if not latex:
            return ConversionResult(
                latex="(conversion failed)",
                source="llm",
                render_ok=False,
                render_error="LLM returned empty",
            )

        # Phase 4: basic validation
        ok, err = self._validate_latex(latex)

        return ConversionResult(
            latex=latex,
            source="llm",
            render_ok=ok,
            render_error=err,
        )

    # ── Phase 1: shorthand ────────────────────────────────────

    @staticmethod
    def _expand_shorthands(text: str) -> str:
        """Expand user-defined shorthands in the input."""
        result = text
        for short, replacement in SHORTHANDS.items():
            if short in result:
                result = result.replace(short, replacement)
        return result

    # ── Phase 2: template matching ────────────────────────────

    @staticmethod
    def _match_template(text: str) -> ConversionResult | None:
        """Exact match against known templates."""
        stripped = text.strip()
        if stripped in TEMPLATES:
            return ConversionResult(
                latex=TEMPLATES[stripped],
                source="template",
                matched_template=stripped,
            )
        return None

    # ── Phase 3: LLM ──────────────────────────────────────────

    def _llm_convert(self, text: str) -> str | None:
        """Call Gemma 4 E4B via Ollama to convert text to LaTeX."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                options={
                    "temperature": 0.1,  # low temp for deterministic output
                    "num_predict": 512,  # formulas are short
                },
            )
            content = response["message"]["content"].strip()
            # Strip any accidental $ wrappers
            if content.startswith("$$") and content.endswith("$$"):
                content = content[2:-2].strip()
            elif content.startswith("$") and content.endswith("$"):
                content = content[1:-1].strip()
            # Strip ```latex blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            return content
        except Exception as e:
            print(f"  ❌ LLM error: {e}")
            return None

    # ── Phase 4: validation ───────────────────────────────────

    @staticmethod
    def _validate_latex(latex: str) -> tuple[bool, str | None]:
        """Basic structural validation of LaTeX output."""
        # Check balanced braces
        depth = 0
        for ch in latex:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if depth < 0:
                return False, "Unmatched closing brace }"
        if depth != 0:
            return False, f"Unmatched opening brace (depth={depth})"

        # Check balanced \begin/\end
        import re

        begins = re.findall(r"\\begin\{(\w+)\}", latex)
        ends = re.findall(r"\\end\{(\w+)\}", latex)
        if sorted(begins) != sorted(ends):
            return False, f"\\begin/\\end mismatch: begin={begins} end={ends}"

        return True, None
