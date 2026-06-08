"""LaTeX Validator — multi-layer syntax checking."""
from __future__ import annotations

import re
import subprocess

from texada.types import CheckResult, ValidationResult


class LaTeXValidator:
    """Multi-layer LaTeX validation — brace balance, env balance, command check, KaTeX parse."""

    def validate(self, latex: str) -> ValidationResult:
        checks = [
            self._check_brace_balance(latex),
            self._check_env_balance(latex),
            self._check_command_validity(latex),
        ]
        # KaTeX check is authoritative but optional (needs npx)
        katex_check = self._check_katex_render(latex)
        if katex_check.ok:
            checks.append(katex_check)
        else:
            # If KaTeX fails but structural checks pass, flag but don't block
            if all(c.ok for c in checks):
                checks.append(CheckResult(ok=False, type="katex_render", detail=katex_check.error))

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
        begins = re.findall(r'\\begin\{(\w+)\}', latex)
        ends = re.findall(r'\\end\{(\w+)\}', latex)
        for env in set(begins):
            if begins.count(env) != ends.count(env):
                missing = begins.count(env) - ends.count(env)
                return CheckResult(ok=False, type="env_unbalanced",
                                   detail=f"\\begin{{{env}}} 有 {begins.count(env)} 个但 "
                                          f"\\end{{{env}}} 只有 {ends.count(env)} 个")
        return CheckResult(ok=True, type="env_balance")

    def _check_command_validity(self, latex: str) -> CheckResult:
        """Check that LaTeX commands are not obviously invalid."""
        # Extract all \xxx commands
        commands = re.findall(r'\\(\w+)', latex)
        invalid = []
        for cmd in commands:
            # Skip known valid commands (this is a fast heuristic, not exhaustive)
            if cmd in ("frac", "int", "iint", "iiint", "oint", "sum", "prod",
                       "lim", "sin", "cos", "tan", "log", "ln", "exp",
                       "sqrt", "partial", "nabla", "det", "begin", "end",
                       "text", "mathrm", "mathbf", "mathcal", "mathbb",
                       "left", "right", "hat", "vec", "tilde", "dot", "bar",
                       "overline", "underline", "frac", "dfrac", "tfrac",
                       "binom", "cases", "pmatrix", "bmatrix", "vmatrix",
                       "alpha", "beta", "gamma", "delta", "epsilon", "theta",
                       "lambda", "mu", "sigma", "phi", "omega",
                       "infty", "forall", "exists", "in", "notin", "subset",
                       "cup", "cap", "emptyset", "neq", "geq", "leq",
                       "Rightarrow", "Leftrightarrow", "rightarrow",
                       "leftarrow", "leftrightarrow", "mapsto",
                       "because", "therefore", "blacksquare", "placeholder"):
                continue
            # Single-letter commands are always valid (\x, \a, etc.)
            if len(cmd) == 1:
                continue
            # Longer unknown commands might be wrong
            if len(cmd) > 8:
                invalid.append(cmd)
        if invalid:
            return CheckResult(ok=False, type="unknown_command",
                               detail=f"可疑命令: {', '.join(invalid)}")
        return CheckResult(ok=True, type="command_validity")

    def _check_katex_render(self, latex: str) -> CheckResult:
        """KaTeX rendering check — authoritative validation."""
        try:
            result = subprocess.run(
                ["npx", "katex", "-F", "tex", "-t"],
                input=latex, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return CheckResult(ok=True, type="katex_render")
            return CheckResult(ok=False, type="katex_render",
                               error=result.stderr.strip()[:200])
        except FileNotFoundError:
            # npx/katex not available — skip this check
            return CheckResult(ok=True, type="katex_render", detail="npx katex not available, skipped")
        except subprocess.TimeoutExpired:
            return CheckResult(ok=False, type="katex_render", error="KaTeX render timeout")