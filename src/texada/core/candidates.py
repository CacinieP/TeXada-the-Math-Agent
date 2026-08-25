"""High-confidence deterministic candidates for common structured inputs."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DeterministicCandidate:
    """A candidate that is safe to validate before invoking the planner."""

    latex: str
    rule: str


class DeterministicCandidateEngine:
    """Extract explicit LaTeX hints and unambiguous structured NL patterns."""

    _COMMAND_NAMES = (
        "iiint",
        "iint",
        "oint",
        "partial",
        "sqrt",
        "frac",
        "prod",
        "sum",
        "lim",
        "int",
    )
    _COMMANDS = "|".join(_COMMAND_NAMES)
    _COMMAND_START = re.compile(
        rf"(?<![A-Za-z\\])\\?(?:{_COMMANDS})(?=\s*(?:[_^{{]))"
    )
    _BARE_COMMAND = re.compile(
        rf"(?<![A-Za-z\\])(?P<name>{_COMMANDS})(?=\s*(?:[_^{{]))"
    )
    _CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    _MATH_STRUCTURE = re.compile(r"[_^{}=+\-*/]")
    _IDENT = r"[A-Za-z][A-Za-z0-9_]*"
    _FUNCTION_EXPRESSION = (
        rf"{_IDENT}(?:\s*\(\s*[A-Za-z]"
        r"(?:\s*,\s*[A-Za-z])*\s*\))?"
    )
    _SUM_RANGE = re.compile(
        r"^\s*(?:求(?:和)?\s*)?"
        r"(?P<index>[A-Za-z])\s*从\s*"
        r"(?P<lower>[-+A-Za-z0-9∞]+)\s*到\s*"
        r"(?P<upper>[-+A-Za-z0-9∞]+)\s*的\s*"
        r"(?P<term>.+?)\s*(?:之和)?\s*$"
    )
    _PARTIAL_PREFIX = re.compile(
        r"^\s*(?:求)?偏导\s*"
        rf"(?P<expression>{_FUNCTION_EXPRESSION})\s*"
        r"(?:关于|对)\s*(?P<variable>[A-Za-z])\s*$"
    )
    _PARTIAL_SUFFIX = re.compile(
        rf"^\s*(?:求)?(?P<expression>{_FUNCTION_EXPRESSION})\s*"
        r"(?:关于|对)\s*(?P<variable>[A-Za-z])\s*的偏导(?:数)?\s*$"
    )
    _LIMIT_QUOTIENT = re.compile(
        r"^\s*(?:求)?(?:当\s*)?(?P<variable>[A-Za-z])\s*"
        r"(?:趋向|趋近于?)\s*"
        r"(?P<point>[-+A-Za-z0-9∞]+)\s*时\s*"
        r"(?P<numerator>.+?)\s*(?:除以|/)\s*"
        r"(?P<denominator>[A-Za-z0-9_]+)\s*的极限\s*$"
    )
    _MULTIPLE_INTEGRAL = re.compile(
        r"^\s*(?P<rank>[二三])重积分\s*"
        r"(?P<function>[A-Za-z][A-Za-z0-9_]*)\s*"
        r"\(\s*(?P<variables>[A-Za-z](?:\s*,\s*[A-Za-z]){1,2})\s*\)\s*"
        r"在(?:区域)?\s*(?P<domain>[A-Za-zΩ])\s*上\s*$"
    )
    _FUNCTION_TERM = re.compile(
        r"^(?P<function>sin|cos|tan|log|ln|exp)\s*"
        r"(?P<argument>[A-Za-z0-9_]+)$"
    )
    _ATOM = r"[A-Za-z0-9_]+"
    _DIVISION = re.compile(
        rf"^\s*(?P<numerator>{_ATOM})\s*除以\s*"
        rf"(?P<denominator>{_ATOM})\s*$"
    )
    _SIMPLE_EQUALITY = re.compile(
        rf"^\s*(?P<left>{_ATOM})\s*"
        rf"(?P<operator>加上?|减去?|乘以?)\s*(?P<right>{_ATOM})\s*"
        rf"等于\s*(?P<result>{_ATOM})\s*$"
    )
    _SUM_POWER = re.compile(
        rf"^\s*(?P<left>{_ATOM})\s*与\s*(?P<right>{_ATOM})\s*"
        r"之和的(?P<power>平方|立方)\s*$"
    )
    _RADICAND = re.compile(
        rf"^\s*根号下\s*(?P<left>{_ATOM})\s*"
        rf"(?:(?P<operator>加上?|减去?|乘以?)\s*"
        rf"(?P<right>{_ATOM}))?\s*$"
    )
    _SIMPLE_SUM_EN = re.compile(
        rf"^\s*(?:(?:write|express|represent|typeset)\s+)?"
        rf"(?:the\s+)?sum of (?P<left>{_ATOM}) and (?P<right>{_ATOM})\s*$",
        re.IGNORECASE,
    )
    _DOT_PRODUCT_EN = re.compile(
        rf"^\s*dot\s+product\s*\(\s*(?P<left>{_IDENT})\s*,\s*"
        rf"(?P<right>{_IDENT})\s*\)\s*$",
        re.IGNORECASE,
    )
    _DOT_PRODUCT_ZH = re.compile(
        rf"^\s*(?:向量\s*)?(?P<left>{_IDENT})\s*(?:和|与)\s*"
        rf"(?P<right>{_IDENT})\s*的?点乘\s*$"
    )
    _INNER_PRODUCT_ZH = re.compile(
        rf"^\s*(?:向量\s*)?(?P<left>{_IDENT})\s*(?:和|与)\s*"
        rf"(?P<right>{_IDENT})\s*的?内积\s*$"
    )
    _TRAILING_PUNCTUATION = " \t\r\n,，。.;；"
    _TRAILING_NL_PUNCTUATION = " \t\r\n,，。.;；!！?？"

    def propose(self, text: str) -> DeterministicCandidate | None:
        """Return a candidate only when a local rule has high confidence."""
        inline = self._inline_latex(text)
        if inline:
            return DeterministicCandidate(
                latex=inline,
                rule="inline_latex_hint",
            )

        structured_text = text.rstrip(self._TRAILING_NL_PUNCTUATION)
        concept = self._canonical_concept(structured_text)
        if concept:
            return DeterministicCandidate(
                latex=concept,
                rule="nl_canonical_concept",
            )

        summation = self._range_sum(structured_text)
        if summation:
            return DeterministicCandidate(
                latex=summation,
                rule="nl_range_sum",
            )
        partial = self._partial_derivative(structured_text)
        if partial:
            return DeterministicCandidate(
                latex=partial,
                rule="nl_partial_derivative",
            )
        quotient_limit = self._quotient_limit(structured_text)
        if quotient_limit:
            return DeterministicCandidate(
                latex=quotient_limit,
                rule="nl_quotient_limit",
            )
        multiple_integral = self._multiple_integral(structured_text)
        if multiple_integral:
            return DeterministicCandidate(
                latex=multiple_integral,
                rule="nl_multiple_integral",
            )
        division = self._division(structured_text)
        if division:
            return DeterministicCandidate(
                latex=division,
                rule="nl_simple_division",
            )
        equality = self._simple_equality(structured_text)
        if equality:
            return DeterministicCandidate(
                latex=equality,
                rule="nl_simple_equality",
            )
        sum_power = self._sum_power(structured_text)
        if sum_power:
            return DeterministicCandidate(
                latex=sum_power,
                rule="nl_sum_power",
            )
        radical = self._radical(structured_text)
        if radical:
            return DeterministicCandidate(
                latex=radical,
                rule="nl_simple_radical",
            )
        simple_sum_en = self._simple_sum_en(structured_text)
        if simple_sum_en:
            return DeterministicCandidate(
                latex=simple_sum_en,
                rule="nl_simple_sum_en",
            )
        return None

    def _inline_latex(self, text: str) -> str:
        stripped = text.strip()
        for pattern in (
            re.compile(r"\$\$(?P<formula>.+?)\$\$\s*$", re.DOTALL),
            re.compile(r"\$(?P<formula>[^$]+)\$\s*$", re.DOTALL),
            re.compile(r"\\\((?P<formula>.+?)\\\)\s*$", re.DOTALL),
            re.compile(r"\\\[(?P<formula>.+?)\\\]\s*$", re.DOTALL),
        ):
            match = pattern.search(stripped)
            if match:
                return self._restore_bare_commands(match.group("formula").strip())

        for match in self._COMMAND_START.finditer(stripped):
            candidate = stripped[match.start():].strip(
                self._TRAILING_PUNCTUATION
            )
            if self._CJK.search(candidate):
                continue
            if not self._MATH_STRUCTURE.search(candidate):
                continue
            return self._restore_bare_commands(candidate)
        return ""

    def _range_sum(self, text: str) -> str:
        match = self._SUM_RANGE.fullmatch(text)
        if not match:
            return ""

        index = match.group("index")
        term = self._simple_term(match.group("term"), index)
        if not term:
            return ""
        lower = self._bound(match.group("lower"))
        upper = self._bound(match.group("upper"))
        return rf"\sum_{{{index}={lower}}}^{{{upper}}} {term}"

    def _partial_derivative(self, text: str) -> str:
        match = self._PARTIAL_PREFIX.fullmatch(text)
        if not match:
            match = self._PARTIAL_SUFFIX.fullmatch(text)
        if not match:
            return ""
        expression = re.sub(r"\s+", "", match.group("expression"))
        variable = match.group("variable")
        return rf"\frac{{\partial {expression}}}{{\partial {variable}}}"

    def _quotient_limit(self, text: str) -> str:
        match = self._LIMIT_QUOTIENT.fullmatch(text)
        if not match:
            return ""
        numerator = self._simple_expression(match.group("numerator"))
        denominator = self._simple_expression(match.group("denominator"))
        if not numerator or not denominator:
            return ""
        variable = match.group("variable")
        point = self._bound(match.group("point"))
        return (
            rf"\lim_{{{variable}\to {point}}} "
            rf"\frac{{{numerator}}}{{{denominator}}}"
        )

    def _multiple_integral(self, text: str) -> str:
        match = self._MULTIPLE_INTEGRAL.fullmatch(text)
        if not match:
            return ""
        variables = [
            item.strip()
            for item in match.group("variables").split(",")
        ]
        expected_rank = 2 if match.group("rank") == "二" else 3
        if len(variables) != expected_rank:
            return ""
        operator = r"\iint" if expected_rank == 2 else r"\iiint"
        function = match.group("function")
        arguments = ",".join(variables)
        differentials = "".join(rf"\,d{variable}" for variable in variables)
        domain = match.group("domain")
        return (
            rf"{operator}_{{{domain}}} "
            rf"{function}({arguments}){differentials}"
        )

    def _division(self, text: str) -> str:
        match = self._DIVISION.fullmatch(text)
        if not match:
            return ""
        return (
            rf"\frac{{{match.group('numerator')}}}"
            rf"{{{match.group('denominator')}}}"
        )

    def _simple_equality(self, text: str) -> str:
        match = self._SIMPLE_EQUALITY.fullmatch(text)
        if not match:
            return ""
        operator_word = match.group("operator")
        operator = (
            "+"
            if operator_word.startswith("加")
            else "-"
            if operator_word.startswith("减")
            else r"\times "
        )
        return (
            f"{match.group('left')}{operator}{match.group('right')}"
            f"={match.group('result')}"
        )

    def _sum_power(self, text: str) -> str:
        match = self._SUM_POWER.fullmatch(text)
        if not match:
            return ""
        power = "2" if match.group("power") == "平方" else "3"
        return rf"({match.group('left')}+{match.group('right')})^{power}"

    def _radical(self, text: str) -> str:
        match = self._RADICAND.fullmatch(text)
        if not match:
            return ""
        radicand = match.group("left")
        if match.group("operator"):
            operator_word = match.group("operator")
            operator = (
                "+"
                if operator_word.startswith("加")
                else "-"
                if operator_word.startswith("减")
                else r"\times "
            )
            radicand += f"{operator}{match.group('right')}"
        return rf"\sqrt{{{radicand}}}"

    def _simple_sum_en(self, text: str) -> str:
        match = self._SIMPLE_SUM_EN.fullmatch(text)
        if not match:
            return ""
        return f"{match.group('left')}+{match.group('right')}"

    def _canonical_concept(self, text: str) -> str:
        """Return a standard formula only for an explicit named concept."""
        dot = self._DOT_PRODUCT_EN.fullmatch(text)
        if not dot:
            dot = self._DOT_PRODUCT_ZH.fullmatch(text)
        if dot:
            return rf"{dot.group('left')} \cdot {dot.group('right')}"

        inner = self._INNER_PRODUCT_ZH.fullmatch(text)
        if inner:
            return (
                rf"\langle {inner.group('left')},"
                rf"{inner.group('right')} \rangle"
            )

        normalized = re.sub(r"\s+", " ", text.strip()).casefold()
        concepts = {
            "inner product": (
                r"\langle \placeholder{},\placeholder{} \rangle"
            ),
            "二重积分": (
                r"\iint_{\placeholder{}} \placeholder{}\,dA"
            ),
            "double integral": (
                r"\iint_{\placeholder{}} \placeholder{}\,dA"
            ),
            "三重积分": (
                r"\iiint_{\placeholder{}} \placeholder{}\,dV"
            ),
            "triple integral": (
                r"\iiint_{\placeholder{}} \placeholder{}\,dV"
            ),
            "分段函数": (
                r"f(x)=\begin{cases}"
                r"\placeholder{},&x\ge 0\\"
                r"\placeholder{},&x<0"
                r"\end{cases}"
            ),
            "piecewise function": (
                r"f(x)=\begin{cases}"
                r"\placeholder{},&x\ge 0\\"
                r"\placeholder{},&x<0"
                r"\end{cases}"
            ),
            "导数定义": (
                r"f'(x)=\lim_{h\to 0}"
                r"\frac{f(x+h)-f(x)}{h}"
            ),
            "导数的极限定义式": (
                r"f'(x)=\lim_{h\to 0}"
                r"\frac{f(x+h)-f(x)}{h}"
            ),
            "极限定义式": r"\lim_{x\to a}f(x)=L",
            "概率密度函数": (
                r"f_X(x)\ge 0,\quad "
                r"\int_{-\infty}^{\infty}f_X(x)\,dx=1"
            ),
            "probability density function": (
                r"f_X(x)\ge 0,\quad "
                r"\int_{-\infty}^{\infty}f_X(x)\,dx=1"
            ),
            "probability denisity function": (
                r"f_X(x)\ge 0,\quad "
                r"\int_{-\infty}^{\infty}f_X(x)\,dx=1"
            ),
            "连续随机变量": (
                r"P(a\le X\le b)=\int_a^b f_X(x)\,dx"
            ),
            "交叉熵损失": (
                r"\mathcal{L}_{CE}=-\sum_{i=1}^{n}"
                r"y_i\log \hat{y}_i"
            ),
            "信息熵公式": r"H(X)=-\sum_i p_i\log p_i",
            "实数域 r": r"\mathbb{R}",
            "贝叶斯公式": (
                r"P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}"
            ),
        }
        return concepts.get(normalized, "")

    @classmethod
    def _restore_bare_commands(cls, candidate: str) -> str:
        return cls._BARE_COMMAND.sub(
            lambda match: rf"\{match.group('name')}",
            candidate,
        )

    @staticmethod
    def _bound(value: str) -> str:
        return (
            value.replace("-∞", r"-\infty")
            .replace("+∞", r"+\infty")
            .replace("∞", r"\infty")
        )

    @staticmethod
    def _simple_term(value: str, index: str) -> str:
        compact = re.sub(r"\s+", "", value)
        escaped_index = re.escape(index)
        if re.fullmatch(rf"{escaped_index}(?:的)?平方", compact):
            return f"{index}^2"
        if re.fullmatch(rf"{escaped_index}(?:的)?立方", compact):
            return f"{index}^3"
        if re.fullmatch(r"[A-Za-z0-9()+\-*/^{}_.]+", compact):
            return compact
        return ""

    @classmethod
    def _simple_expression(cls, value: str) -> str:
        compact = re.sub(r"\s+", " ", value.strip())
        function = cls._FUNCTION_TERM.fullmatch(compact)
        if function:
            return (
                rf"\{function.group('function')} "
                f"{function.group('argument')}"
            )
        if re.fullmatch(r"[A-Za-z0-9_]+", compact):
            return compact
        return ""
