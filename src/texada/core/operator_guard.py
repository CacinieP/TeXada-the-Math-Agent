"""Low-cost operator-preservation guard for small local planners."""

from __future__ import annotations

import re


class OperatorDriftGuard:
    """Detect loss or downgrade of deterministic SymbolEngine anchors."""

    INTEGRAL_LADDER: tuple[str, ...] = (r"\int", r"\oint", r"\iint", r"\iiint")
    STANDALONE_OPS: tuple[str, ...] = (
        r"\sum",
        r"\prod",
        r"\lim",
        r"\frac",
        r"\partial",
    )

    def integral_rank(self, text: str) -> int:
        """Return the strongest integral rank present, or zero."""
        rank = 0
        for index, operator in enumerate(self.INTEGRAL_LADDER, start=1):
            if operator in text:
                rank = index
        return rank

    def check(self, preprocessed: str, model_output: str) -> bool:
        """Return true when an anchored operator was lost or downgraded."""
        if not model_output:
            return False

        input_rank = self.integral_rank(preprocessed)
        output_rank = self.integral_rank(model_output)
        if input_rank > 0 and output_rank < input_rank:
            return True

        return any(
            operator in preprocessed and operator not in model_output
            for operator in self.STANDALONE_OPS
        )

    def forced_operators(self, preprocessed: str) -> list[str]:
        """Return the minimal operator anchors required in a retry."""
        forced: list[str] = []
        input_rank = self.integral_rank(preprocessed)
        if input_rank:
            forced.append(self.INTEGRAL_LADDER[input_rank - 1])
        forced.extend(
            operator for operator in self.STANDALONE_OPS if operator in preprocessed
        )
        return forced

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
