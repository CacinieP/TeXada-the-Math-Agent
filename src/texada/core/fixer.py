"""LaTeX Fixer — auto-repair common model output errors without re-invoking model."""
from __future__ import annotations

import re

from texada.types import CheckResult, FixResult

# Common model confusion mappings
COMMAND_FIXES: dict[str, str] = {
    r"\begin{array}": r"\begin{aligned}",
    r"\end{array}": r"\end{aligned}",
    r"\begin{equation*}": r"\begin{aligned}",
    r"\end{equation*}": r"\end{aligned}",
}


class LaTeXFixer:
    """Auto-repair LaTeX errors — no model calls needed."""

    def fix(self, latex: str, errors: list[CheckResult]) -> FixResult:
        fixed = latex
        fix_log: list[str] = []

        for error in errors:
            if error.type == "brace_unbalanced":
                result, log = self._fix_braces(fixed)
                fixed = result
                if log:
                    fix_log.append(log)
            elif error.type == "env_unbalanced":
                result, log = self._fix_env(fixed)
                fixed = result
                if log:
                    fix_log.append(log)
            elif error.type == "unknown_command":
                result, log = self._fix_command(fixed, error.detail)
                fixed = result
                if log:
                    fix_log.append(log)

        return FixResult(latex=fixed, fixed=bool(fix_log), log=fix_log)

    def _fix_braces(self, latex: str) -> tuple[str, str]:
        """Auto-complete missing closing braces. Extra closing braces cannot be safely auto-fixed."""
        depth = 0
        for ch in latex:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
        if depth > 0:
            return latex + '}' * depth, f"补全 {depth} 个 }}"
        # depth < 0: extra closing braces — cannot reliably determine where
        # the missing opening brace should go. Better to leave for manual fix.
        return latex, ""

    def _fix_env(self, latex: str) -> tuple[str, str]:
        """Auto-complete missing \\end{...}."""
        begins = re.findall(r'\\begin\{(\w+)\}', latex)
        ends = re.findall(r'\\end\{(\w+)\}', latex)
        missing = []
        for env in set(begins):
            deficit = begins.count(env) - ends.count(env)
            if deficit > 0:
                for _ in range(deficit):
                    latex += f'\\end{{{env}}}'
                    missing.append(env)
        if missing:
            return latex, f"补全 \\end{{{', '.join(set(missing))}}}"
        return latex, ""

    def _fix_command(self, latex: str, detail: str) -> tuple[str, str]:
        """Replace known erroneous commands."""
        fixes_applied = []
        for bad, good in COMMAND_FIXES.items():
            if bad in latex:
                latex = latex.replace(bad, good)
                fixes_applied.append(f"{bad} → {good}")
        if fixes_applied:
            return latex, f"替换: {', '.join(fixes_applied)}"
        return latex, ""