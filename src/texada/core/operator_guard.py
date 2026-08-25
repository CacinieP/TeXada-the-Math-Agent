"""Low-cost operator-preservation guard for small local planners."""

from __future__ import annotations

import re


class OperatorDriftGuard:
    """Detect loss or downgrade of deterministic and request-level anchors."""

    INTEGRAL_LADDER: tuple[str, ...] = (r"\int", r"\oint", r"\iint", r"\iiint")
    STANDALONE_OPS: tuple[str, ...] = (
        r"\sum",
        r"\prod",
        r"\lim",
        r"\frac",
        r"\partial",
    )
    REQUEST_OPERATOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\bfraction\b", re.IGNORECASE), r"\frac"),
        (re.compile(r"\b(?:indefinite|definite)?\s*integral\b", re.IGNORECASE), r"\int"),
        (
            re.compile(r"(?<!lower )(?<!upper )\blimit\b", re.IGNORECASE),
            r"\lim",
        ),
        (re.compile(r"\bsquare root\b", re.IGNORECASE), r"\sqrt"),
        (re.compile(r"\bhyperbolic tangent\b", re.IGNORECASE), r"\tanh"),
        (re.compile(r"\bhyperbolic sine\b", re.IGNORECASE), r"\sinh"),
        (re.compile(r"\bhyperbolic cosine\b", re.IGNORECASE), r"\cosh"),
        (re.compile(r"\binverse tangent\b", re.IGNORECASE), r"\arctan"),
        (re.compile(r"\binverse sine\b", re.IGNORECASE), r"\arcsin"),
        (re.compile(r"\binverse cosine\b", re.IGNORECASE), r"\arccos"),
        (
            re.compile(
                r"(?<!hyperbolic )(?<!inverse )\btangent(?:\s+function)?\b",
                re.IGNORECASE,
            ),
            r"\tan",
        ),
        (
            re.compile(
                r"(?<!hyperbolic )(?<!inverse )\bsine(?:\s+function)?\b",
                re.IGNORECASE,
            ),
            r"\sin",
        ),
        (
            re.compile(
                r"(?<!hyperbolic )(?<!inverse )\bcosine(?:\s+function)?\b",
                re.IGNORECASE,
            ),
            r"\cos",
        ),
        (re.compile(r"\bexponential function\b", re.IGNORECASE), r"\exp"),
        (re.compile(r"\bnatural logarithm\b", re.IGNORECASE), r"\ln"),
        (re.compile(r"\bcentered dot\b", re.IGNORECASE), r"\cdot"),
        (re.compile(r"\bgreater than or equal to\b", re.IGNORECASE), r"\ge"),
        (re.compile(r"\bless than or equal to\b", re.IGNORECASE), r"\le"),
        (re.compile(r"\bnot equal to\b", re.IGNORECASE), r"\ne"),
        (re.compile(r"\bCartesian product\b", re.IGNORECASE), r"\times"),
        (re.compile(r"\bunion\b", re.IGNORECASE), r"\cup"),
        (re.compile(r"\bintersection\b", re.IGNORECASE), r"\cap"),
        (re.compile(r"\bset difference\b", re.IGNORECASE), r"\setminus"),
        (re.compile(r"\bpartial derivative\b", re.IGNORECASE), r"\partial"),
        (re.compile(r"\bderivative with respect to\b", re.IGNORECASE), r"\frac"),
        (re.compile(r"\bnormal distribution\b", re.IGNORECASE), r"\mathcal{N}"),
        (re.compile(r"\bfollows a normal distribution\b", re.IGNORECASE), r"\sim"),
        (re.compile(r"\bbold vector\b", re.IGNORECASE), r"\mathbf"),
        (re.compile(r"\bpiecewise\b", re.IGNORECASE), r"\begin{cases}"),
        (
            re.compile(r"\bmatrix in parentheses\b", re.IGNORECASE),
            r"\begin{pmatrix}",
        ),
    )
    GREEK_NAMES: tuple[str, ...] = (
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
        "theta", "iota", "kappa", "lambda", "mu", "nu", "xi",
        "pi", "rho", "sigma", "tau", "upsilon", "phi",
        "chi", "psi", "omega",
    )
    UPPERCASE_GREEK: frozenset[str] = frozenset(
        {
            "gamma", "delta", "theta", "lambda", "xi", "pi", "sigma",
            "upsilon", "phi", "psi", "omega",
        }
    )

    def integral_rank(self, text: str) -> int:
        """Return the strongest integral rank present, or zero."""
        rank = 0
        for index, operator in enumerate(self.INTEGRAL_LADDER, start=1):
            if operator in text:
                rank = index
        return rank

    def check(
        self,
        preprocessed: str,
        model_output: str,
        *,
        user_input: str = "",
    ) -> bool:
        """Return true when an anchored operator was lost or downgraded."""
        if not model_output:
            return False

        input_rank = self.integral_rank(preprocessed)
        output_rank = self.integral_rank(model_output)
        if input_rank > 0 and output_rank < input_rank:
            return True

        return bool(
            self.missing_requirements(
                preprocessed,
                model_output,
                user_input=user_input,
            )
        )

    def forced_operators(
        self,
        preprocessed: str,
        user_input: str = "",
    ) -> list[str]:
        """Return the minimal operator anchors required in a retry."""
        forced: list[str] = []
        input_rank = self.integral_rank(preprocessed)
        if input_rank:
            forced.append(self.INTEGRAL_LADDER[input_rank - 1])
        forced.extend(
            operator for operator in self.STANDALONE_OPS if operator in preprocessed
        )
        request = user_input.strip()
        for pattern, operator in self.REQUEST_OPERATOR_PATTERNS:
            if pattern.search(request):
                forced.append(operator)

        for name in self.GREEK_NAMES:
            if re.search(
                rf"\b(?:lowercase(?:\s+Greek(?:\s+letter)?)?"
                rf"|Greek(?:\s+letter)?)\s+{name}\b",
                request,
                re.IGNORECASE,
            ):
                forced.append(rf"\{name}")
            elif (
                name in self.UPPERCASE_GREEK
                and re.search(
                    rf"\buppercase\s+{name}\b",
                    request,
                    re.IGNORECASE,
                )
            ):
                forced.append("\\" + name.capitalize())
        if re.search(r"\bmean\s+(?:is\s+)?mu\b", request, re.I):
            forced.append(r"\mu")
        if re.search(r"\bvariance\s+(?:is\s+)?sigma\b", request, re.I):
            forced.append(r"\sigma")

        if re.search(r"\b(?:sum|summation)\s+(?:over|from)\b", request, re.I):
            forced.append(r"\sum")
        elif re.search(
            r"\bsum of (?:the\s+)?[A-Za-z0-9]+ and (?:the\s+)?"
            r"[A-Za-z0-9]+\b",
            request,
            re.IGNORECASE,
        ):
            forced.append("+")
        indexed_product = bool(
            not re.search(r"\bCartesian product\b", request, re.IGNORECASE)
            and re.search(r"\bproduct\s+(?:over|from)\b", request, re.I)
        )
        if indexed_product:
            forced.append(r"\prod")
        if (
            re.search(r"\bmultiplication sign\b", request, re.I)
            and not re.search(r"\bcentered dot\b", request, re.I)
            and not re.search(
                r"\b(?:without|no)\s+(?:an?\s+)?(?:explicit\s+)?"
                r"multiplication sign\b",
                request,
                re.IGNORECASE,
            )
        ):
            forced.append(r"\times")
        if (
            re.search(r"\bdifference of\b", request, re.I)
            and re.search(
                r"\b(?:set expression|Cartesian product|union|intersection)\b",
                request,
                re.IGNORECASE,
            )
        ):
            forced.append(r"\setminus")
        if re.search(r"\bsubscript\b", request, re.I):
            forced.append("_")
        subscript_patterns = (
            r"\b(?:symbol\s+|variable\s+)?(?P<base>[A-Za-z])\s+with\s+"
            r"(?:a\s+)?subscript\s+(?P<sub>[A-Za-z])\b",
            r"(?<!with )\b(?P<base>[A-Za-z])\s+sub(?:script)?\s+"
            r"(?P<sub>[A-Za-z])\b",
        )
        for pattern in subscript_patterns:
            for match in re.finditer(pattern, request, re.IGNORECASE):
                forced.append(
                    f"{match.group('base')}_{{{match.group('sub')}}}"
                )
        if re.search(r"(?<!half-)\bopen interval\b", request, re.I):
            forced.append("(...)")
        if (
            (
                re.search(r"\bequality\b", request, re.I)
                and not re.search(r"\bno equality\b", request, re.I)
            )
            or (
                re.search(r"\bequals\b", request, re.I)
                and not re.search(
                    r"\b(?:integral|no equality)\b",
                    request,
                    re.IGNORECASE,
                )
            )
        ):
            forced.append("=")

        if re.search(r"\b(?:interval|set of (?:all )?numbers)\b", request, re.I):
            forced = [item for item in forced if item not in {r"\ge", r"\le"}]

        derivative = re.search(
            r"\b(?P<order>first|second|third) derivative with respect to "
            r"(?P<variable>[A-Za-z]) of (?:the function )?"
            r"(?P<function>[A-Za-z])\b",
            request,
            re.IGNORECASE,
        )
        if derivative:
            forced.extend(
                [
                    derivative.group("function"),
                    derivative.group("variable"),
                    f"{derivative.group('order').lower()}-order derivative",
                ]
            )

        transpose = re.search(
            r"\btranspose of uppercase\s+(?P<symbol>[A-Za-z])\b",
            request,
            re.IGNORECASE,
        )
        if transpose:
            forced.append(f"{transpose.group('symbol').upper()}^{{T}}")

        grouped_power = re.search(
            r"\bnumber (?P<base>\d+) raised to the power.*?"
            r"variable (?P<variable>[A-Za-z]) with subscript (?P<sub>[A-Za-z])"
            r".*?plus (?P<term>\d+)\b",
            request,
            re.IGNORECASE,
        )
        if grouped_power:
            forced.append(
                f"{grouped_power.group('base')}^{{"
                f"{grouped_power.group('variable')}_{{{grouped_power.group('sub')}}}"
                f"+{grouped_power.group('term')}}}"
            )

        if re.search(r"\bimplicit (?:product|multiplication)\b", request, re.I):
            forced.append("implicit multiplication")

        return list(dict.fromkeys(forced))

    def missing_requirements(
        self,
        preprocessed: str,
        model_output: str,
        *,
        user_input: str = "",
    ) -> list[str]:
        """Return request anchors absent from a non-empty candidate."""
        required = self.forced_operators(preprocessed, user_input)
        return [
            anchor
            for anchor in required
            if not self._anchor_present(
                anchor,
                model_output,
                user_input=user_input,
            )
        ]

    def _anchor_present(
        self,
        anchor: str,
        candidate: str,
        *,
        user_input: str = "",
    ) -> bool:
        """Check exact commands plus the few structural request anchors."""
        if anchor in self.INTEGRAL_LADDER:
            rank_preserved = self.integral_rank(candidate) >= (
                self.INTEGRAL_LADDER.index(anchor) + 1
            )
            if not rank_preserved:
                return False
            if anchor == r"\int" and r"\frac" in self.forced_operators(
                "",
                user_input,
            ):
                integral_positions = [
                    position
                    for operator in self.INTEGRAL_LADDER
                    if (position := candidate.find(operator)) >= 0
                ]
                integral = min(integral_positions, default=-1)
                fraction = candidate.find(r"\frac")
                return integral >= 0 and fraction >= 0 and integral < fraction
            return True
        if anchor == "_":
            return "_" in candidate
        if anchor == "implicit multiplication":
            return not bool(re.search(r"\\(?:cdot|times)\b|\*", candidate))
        if anchor == "(...)":
            return bool(re.search(r"\([^()]*,[^()]*\)", candidate))
        derivative_orders = {
            "first-order derivative",
            "second-order derivative",
            "third-order derivative",
        }
        if anchor in derivative_orders:
            required_count = {
                "first-order derivative": 0,
                "second-order derivative": 2,
                "third-order derivative": 2,
            }[anchor]
            order = {"first": "1", "second": "2", "third": "3"}[
                anchor.split("-", 1)[0]
            ]
            return required_count == 0 or len(
                re.findall(rf"\^(?:\{{{order}\}}|{order})(?!\d)", candidate)
            ) >= required_count
        grouped_power = re.fullmatch(
            r"(?P<base>\d+)\^\{(?P<variable>[A-Za-z])_\{(?P<sub>[A-Za-z])\}"
            r"\+(?P<term>\d+)\}",
            anchor,
        )
        if grouped_power:
            values = {
                key: re.escape(value)
                for key, value in grouped_power.groupdict().items()
            }
            return bool(
                re.search(
                    rf"{values['base']}\s*\^\s*\{{\s*{values['variable']}\s*_"
                    rf"\s*(?:{values['sub']}|\{{\s*{values['sub']}\s*\}})\s*\+"
                    rf"\s*{values['term']}\s*\}}",
                    candidate,
                )
            )
        transpose = re.fullmatch(r"([A-Za-z])\^\{T\}", anchor)
        if transpose:
            symbol = re.escape(transpose.group(1))
            return bool(
                re.search(
                    rf"{symbol}\s*\^\s*(?:T|\{{(?:\\mathsf\{{)?T(?:\}})?\}})",
                    candidate,
                )
            )
        subscript = re.fullmatch(r"([A-Za-z])_\{([A-Za-z])\}", anchor)
        if subscript:
            base, sub = map(re.escape, subscript.groups())
            return bool(
                re.search(
                    rf"{base}\s*_(?:\{{{sub}(?:[^}}]*)\}}|{sub})",
                    candidate,
                )
            )
        if anchor == r"\epsilon":
            return bool(re.search(r"\\varepsilon|\\epsilon", candidate))
        if anchor == r"\frac":
            return self._has_braced_arguments(candidate, anchor, count=2)
        if anchor == r"\cdot" and re.search(r"\bcentered dot\b", user_input, re.I):
            return r"\cdot" in candidate and not bool(
                re.search(r"\\times\b|\*", candidate)
            )
        if anchor == r"\begin{pmatrix}":
            return bool(
                r"\begin{pmatrix}" in candidate
                or (
                    r"\begin{array}" in candidate
                    and bool(re.search(r"\\left\s*\(", candidate))
                    and bool(re.search(r"\\right\s*\)", candidate))
                )
            )
        if anchor in {r"\ge", r"\le"} and re.search(
            r"\bpiecewise\b",
            user_input,
            re.IGNORECASE,
        ):
            return bool(re.search(r"\\(?:geq?|leq?)(?![A-Za-z])", candidate))
        if re.fullmatch(r"\\[A-Za-z]+", anchor):
            aliases = {
                r"\lim": r"\\lim(?:inf|sup)?(?![A-Za-z])",
                r"\ge": r"\\ge(?:q)?(?![A-Za-z])",
                r"\le": r"\\le(?:q)?(?![A-Za-z])",
                r"\ne": r"\\ne(?:q)?(?![A-Za-z])",
            }
            return bool(
                re.search(
                    aliases.get(
                        anchor,
                        re.escape(anchor) + r"(?![A-Za-z])",
                    ),
                    candidate,
                )
            )
        if re.fullmatch(r"[A-Za-z]", anchor):
            return bool(
                re.search(
                    rf"(?<![A-Za-z\\]){re.escape(anchor)}(?![A-Za-z])",
                    candidate,
                    re.IGNORECASE,
                )
            )
        return anchor in candidate

    @staticmethod
    def _has_braced_arguments(candidate: str, command: str, *, count: int) -> bool:
        """Return whether ``command`` is followed by ``count`` balanced groups."""
        start = candidate.find(command)
        if start < 0:
            return False
        cursor = start + len(command)
        for _ in range(count):
            while cursor < len(candidate) and candidate[cursor].isspace():
                cursor += 1
            if cursor >= len(candidate) or candidate[cursor] != "{":
                return False
            depth = 0
            while cursor < len(candidate):
                char = candidate[cursor]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        cursor += 1
                        break
                cursor += 1
            if depth != 0:
                return False
        return True

    def normalize_candidate(self, latex: str) -> str:
        """Canonicalize common MiniCPM/Ollama wrappers, escaping, and aliases."""
        normalized = latex.strip()
        document = re.search(
            r"\\+begin\{document\}(.*?)\\+end\{document\}",
            normalized,
            re.DOTALL,
        )
        if document:
            normalized = document.group(1).strip()
        normalized = re.sub(
            r"\\+(?:section|subsection|subsubsection)\*?\{[^{}]*\}",
            "",
            normalized,
        ).strip()
        if r"\begin{" not in normalized:
            normalized = re.sub(
                r"\\{2,}(?=[A-Za-z])",
                lambda _: "\\",
                normalized,
            )
            normalized = re.sub(
                r"\\\\,\s*",
                lambda _: r"\,",
                normalized,
            )
        normalized = re.sub(
            r"\\int\s*\\int\s*\\int",
            lambda _: r"\iiint",
            normalized,
        )
        return re.sub(
            r"\\int\s*\\int",
            lambda _: r"\iint",
            normalized,
        )

    def restore_required_operators(self, preprocessed: str, candidate: str) -> str:
        """Restore an authoritative integral rank after a model downgrade.

        Standalone operators are not synthesized because their argument
        structure cannot be inferred safely. Integral rank is the exception:
        SymbolEngine already established the intended arity, so replacing the
        first lower-rank integral is deterministic.
        """
        normalized = self.normalize_candidate(candidate)
        required_rank = self.integral_rank(preprocessed)
        current_rank = self.integral_rank(normalized)
        if required_rank == 0:
            return normalized
        required = self.INTEGRAL_LADDER[required_rank - 1]
        if required_rank <= current_rank:
            if required_rank == current_rank:
                canonical = self._integral_fallback(preprocessed, required)
                if canonical and self._integral_structure_drifted(
                    normalized,
                    required,
                    canonical,
                ):
                    return canonical
            return normalized
        if current_rank == 0:
            synthesized = self._integral_fallback(preprocessed, required)
            return synthesized or normalized
        restored = re.sub(
            r"\\(?:iiint|iint|oint|int)(?![A-Za-z])",
            lambda _: required,
            normalized,
            count=1,
        )
        canonical = self._integral_fallback(preprocessed, required)
        if canonical and self._integral_structure_drifted(
            restored,
            required,
            canonical,
        ):
            return canonical
        return restored

    @staticmethod
    def _integral_structure_drifted(
        candidate: str,
        operator: str,
        canonical: str,
    ) -> bool:
        """Detect a missing domain anchor or leaked natural-language prose."""
        domain_match = re.search(r"_\{([^{}]+)\}", canonical)
        if not domain_match:
            return False
        domain = re.escape(domain_match.group(1))
        has_domain = bool(
            re.search(
                re.escape(operator)
                + rf"\s*_(?:\{{{domain}\}}|{domain})(?![A-Za-z0-9_])",
                candidate,
            )
        )
        leaked_prose = bool(
            re.search(
                r"(?:\bin\s+(?:the\s+)?region\b|在(?:区域)?\s*[A-Za-z]\s*上)",
                candidate,
                re.IGNORECASE,
            )
        )
        return not has_domain or leaked_prose

    @staticmethod
    def _integral_fallback(preprocessed: str, operator: str) -> str:
        """Build a narrow fallback for ``<integrand> 在区域 <D> 上``."""
        tail_match = re.search(re.escape(operator) + r"\s*(.+)", preprocessed)
        if not tail_match:
            return ""
        region_match = re.search(
            r"(?P<integrand>.+?)\s*在(?:区域\s*)?"
            r"(?P<domain>[A-Za-z][A-Za-z0-9_]*)\s*上",
            tail_match.group(1),
        )
        if not region_match:
            return ""
        integrand = region_match.group("integrand").strip()
        domain = region_match.group("domain")
        dimension = {
            r"\int": 1,
            r"\oint": 1,
            r"\iint": 2,
            r"\iiint": 3,
        }.get(operator, 0)
        variables: list[str] = []
        args_match = re.search(r"\(([^()]*)\)", integrand)
        if args_match:
            variables = [
                item.strip()
                for item in args_match.group(1).split(",")
                if re.fullmatch(r"[A-Za-z]", item.strip())
            ]
        defaults = ["x", "y", "z"]
        variables = (variables + defaults)[:dimension]
        differentials = "".join(rf"\,d{variable}" for variable in variables)
        return rf"{operator}_{{{domain}}} {integrand}{differentials}"
