"""LaTeX Validator — structural, content, and in-process KaTeX checking."""
from __future__ import annotations

import re

from texada.semantic.katex import shared_katex_parser
from texada.types import CheckResult, ValidationResult


class LaTeXValidator:
    """Validate formula syntax and reject obvious prose masquerading as math."""

    _TEXT_COMMAND = re.compile(
        r"\\(?:text|textbf|textit|textrm|textsf|texttt|mathrm|operatorname)"
        r"\s*\{[^{}]*\}",
        re.DOTALL,
    )
    _CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    _WORD = re.compile(r"[A-Za-z]{2,}")
    _MATH_SIGNAL = re.compile(r"[\\=+\-*/^_<>&|()[\]{}]|\d")
    _SENTENCE_PUNCTUATION = re.compile(r"[?!。？！：:]")
    # A mathematical comparison such as ``m<o\vee m>f`` is not markup.  Tag
    # detection therefore requires a plausible XML/HTML tag name and closing
    # delimiter instead of treating every ``<...>`` span as a tag.
    _MARKUP = re.compile(
        r"<!\[CDATA\[|</?[A-Za-z][A-Za-z0-9:_-]*"
        r"(?:\s+[A-Za-z_:][^<>]*)?\s*/?>",
        re.IGNORECASE,
    )
    _FACTORIAL = re.compile(r"(?<=[A-Za-z0-9}\)])!+")
    _ENV_TOKEN = re.compile(
        r"\\(?P<kind>begin|end)\{(?P<environment>[^{}]+)\}"
    )
    _EMPTY_STRUCTURES: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "empty_fraction_numerator",
            re.compile(r"\\(?:d?frac|tfrac)\s*\{\s*\}\s*\{", re.DOTALL),
        ),
        (
            "empty_fraction_denominator",
            re.compile(r"\\(?:d?frac|tfrac)\s*\{[^{}]*\}\s*\{\s*\}", re.DOTALL),
        ),
        (
            "empty_radicand",
            re.compile(r"\\sqrt(?:\s*\[[^\]]*\])?\s*\{\s*\}", re.DOTALL),
        ),
        ("empty_subscript", re.compile(r"_\s*\{\s*\}")),
        ("empty_superscript", re.compile(r"\^\s*\{\s*\}")),
    )

    def has_formula_content(self, latex: str) -> bool:
        """Return whether text looks like formula content rather than prose."""
        return self._check_formula_content(latex).ok

    def validate(self, latex: str) -> ValidationResult:
        # Empty string is never valid LaTeX
        if not latex.strip():
            return ValidationResult(
                valid=False,
                errors=[CheckResult(ok=False, type="empty", detail="模型输出为空")],
            )
        checks = [
            self._check_brace_balance(latex),
            self._check_env_balance(latex),
            self._check_formula_content(latex),
            self._check_nonempty_structures(latex),
            self._check_katex_parse(latex),
        ]

        return ValidationResult(
            valid=all(c.ok for c in checks),
            errors=[c for c in checks if not c.ok],
        )

    def _check_brace_balance(self, latex: str) -> CheckResult:
        depth = 0
        for i, ch in enumerate(latex):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            if depth < 0:
                return CheckResult(ok=False, type="brace_unbalanced",
                                   detail=f"多余的 }} 在位置 {i}")
        if depth > 0:
            return CheckResult(ok=False, type="brace_unbalanced",
                               detail=f"缺失 {depth} 个 }}")
        return CheckResult(ok=True, type="brace_balance")

    def _check_env_balance(self, latex: str) -> CheckResult:
        stack: list[str] = []
        for match in self._ENV_TOKEN.finditer(latex):
            environment = match.group("environment")
            if match.group("kind") == "begin":
                stack.append(environment)
                continue
            if not stack:
                return CheckResult(ok=False, type="env_unbalanced",
                                   detail=f"多余的 \\end{{{environment}}}")
            expected = stack.pop()
            if environment != expected:
                return CheckResult(
                    ok=False,
                    type="env_unbalanced",
                    detail=(
                        f"环境不匹配：期望 \\end{{{expected}}}，"
                        f"实际为 \\end{{{environment}}}"
                    ),
                )
        if stack:
            environment = stack[-1]
            return CheckResult(
                ok=False,
                type="env_unbalanced",
                detail=f"缺失 \\end{{{environment}}}",
            )
        return CheckResult(ok=True, type="env_balance")

    def _check_formula_content(self, latex: str) -> CheckResult:
        """Reject explanatory prose while allowing text inside explicit text commands."""
        stripped = latex.strip()
        if stripped in {"...", "…", r"\cdots", r"\ldots"}:
            return CheckResult(
                ok=False,
                type="non_formula_content",
                detail="输出只有省略号，不是可用的数学公式",
            )
        if self._MARKUP.search(stripped):
            return CheckResult(
                ok=False,
                type="non_formula_content",
                detail="公式中混入了 HTML/XML 标记",
            )
        outside_text = self._TEXT_COMMAND.sub("", latex)
        if self._CJK.search(outside_text):
            return CheckResult(
                ok=False,
                type="non_formula_content",
                detail="公式包含未放入 \\text{...} 的中文说明文字",
            )
        # ``:=`` and postfix ``!`` are mathematical operators, not prose
        # punctuation.  Keep the sentence guard for a bare colon/question/
        # exclamation mark after removing only those unambiguous math uses.
        punctuation_probe = outside_text.replace(":=", "")
        punctuation_probe = self._FACTORIAL.sub("", punctuation_probe)
        if self._SENTENCE_PUNCTUATION.search(punctuation_probe):
            return CheckResult(
                ok=False,
                type="non_formula_content",
                detail="输出看起来是说明句，而不是纯数学公式",
            )

        words = self._WORD.findall(outside_text)
        signals = self._MATH_SIGNAL.findall(outside_text)
        if len(words) >= 4 and len(signals) < 2:
            return CheckResult(
                ok=False,
                type="non_formula_content",
                detail="输出包含过多自然语言文字",
            )
        return CheckResult(ok=True, type="formula_content")

    def _check_nonempty_structures(self, latex: str) -> CheckResult:
        """Reject syntactically closed but semantically empty formula slots."""
        if r"\placeholder" in latex:
            return CheckResult(ok=True, type="nonempty_structures")
        for error_type, pattern in self._EMPTY_STRUCTURES:
            if pattern.search(latex):
                return CheckResult(
                    ok=False,
                    type=error_type,
                    detail="公式仍包含空的结构参数，请补全内容或使用 \\placeholder{}",
                )
        return CheckResult(ok=True, type="nonempty_structures")

    def _check_katex_parse(self, latex: str) -> CheckResult:
        """Use the vendored in-process KaTeX parser as the single syntax authority."""
        try:
            result = shared_katex_parser().parse(latex)
        except Exception as exc:
            return CheckResult(
                ok=False,
                type="katex_parse",
                error=f"KaTeX parser unavailable: {exc}",
            )
        if result.ok:
            return CheckResult(ok=True, type="katex_parse")
        return CheckResult(
            ok=False,
            type="katex_parse",
            error=result.error[:500],
        )
