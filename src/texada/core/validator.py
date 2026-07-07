"""LaTeX Validator — multi-layer syntax checking."""
from __future__ import annotations

import re
import subprocess

from texada.types import CheckResult, ValidationResult


class LaTeXValidator:
    """Multi-layer LaTeX validation — brace balance, env balance, command check, KaTeX parse."""

    # Known valid commands — replaces the old inline tuple + length heuristic
    _KNOWN_COMMANDS: frozenset[str] = frozenset({
        # Math operators
        "frac", "dfrac", "tfrac", "sqrt", "binom",
        "int", "iint", "iiint", "oint", "sum", "prod", "lim",
        "sin", "cos", "tan", "log", "ln", "exp",
        "partial", "nabla", "det",
        # Text / font
        "text", "mathrm", "mathbf", "mathcal", "mathbb", "mathscr",
        "operatorname",
        # Delimiters
        "left", "right", "begin", "end",
        # Decorations
        "hat", "vec", "tilde", "dot", "bar", "ddot",
        "overline", "underline", "overrightarrow", "overleftarrow",
        "widehat", "widetilde", "overbrace", "underbrace",
        # Environments
        "cases", "pmatrix", "bmatrix", "vmatrix", "aligned", "array",
        # Greek letters
        "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon",
        "zeta", "eta", "theta", "vartheta", "iota", "kappa",
        "lambda", "mu", "nu", "xi", "pi", "rho", "sigma",
        "tau", "upsilon", "phi", "chi", "psi", "omega",
        "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi",
        "Sigma", "Upsilon", "Phi", "Psi", "Omega",
        # Relations / symbols
        "infty", "forall", "exists", "in", "notin", "subset",
        "subsetneq", "supset", "cup", "cap", "emptyset",
        "neq", "geq", "leq", "gg", "ll", "approx", "propto", "sim",
        "Rightarrow", "Leftrightarrow", "rightarrow", "leftarrow",
        "leftrightarrow", "mapsto", "implies",
        "because", "therefore", "blacksquare", "placeholder",
        "cdots", "vdots", "ddots", "ldots",
        "quad", "qquad", "cdot", "times", "div",
        # Long valid commands (> 8 chars)
        "displaystyle", "phantom", "overleftrightarrow",
        "stackrel", "substack", "overset", "underset",
        "textbf", "textit", "textrm", "textsf", "texttt",
    })

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
                return CheckResult(ok=False, type="env_unbalanced",
                                   detail=f"\\begin{{{env}}} 有 {begins.count(env)} 个但 "
                                          f"\\end{{{env}}} 只有 {ends.count(env)} 个")
        return CheckResult(ok=True, type="env_balance")

    def _check_command_validity(self, latex: str) -> CheckResult:
        """Check that LaTeX commands are not obviously invalid."""
        # LaTeX command names are letters only: `\` followed by `[A-Za-z]+`.
        # Using `\w` would wrongly include `_` and swallow the subscript,
        # e.g. matching `\partial_i` as command name "partial_i", or `\int_0`
        # as "int_0" — flagging perfectly valid LaTeX as unknown commands.
        commands = re.findall(r'\\([A-Za-z]+)', latex)
        invalid = []
        for cmd in commands:
            if cmd in self._KNOWN_COMMANDS:
                continue
            # Single-letter commands are always valid (\x, \a, etc.)
            if len(cmd) == 1:
                continue
            # Unknown multi-char commands might be wrong
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
            return CheckResult(
                ok=True,
                type="katex_render",
                detail="npx katex not available, skipped",
            )
        except subprocess.TimeoutExpired:
            return CheckResult(ok=False, type="katex_render", error="KaTeX render timeout")
