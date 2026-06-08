"""LaTeX Syntax Highlighter — pure LaTeX mode structural color annotation."""
from __future__ import annotations

import html


class LaTeXHighlighter:
    """Tokenize LaTeX by semantic role, output color-annotated HTML.

    Color mapping (matches ui-mockup.html):
      structural  → purple (\\frac, \\int, \\sum, \\partial, ...)
      operator    → orange (variables: x, y, f, ...)
      frac        → green (\\frac, \\dfrac, \\tfrac)
      delimiter   → gray ({, }, _, ^, (, ))
    """

    FRAC_COMMANDS = frozenset({r"\frac", r"\dfrac", r"\tfrac"})

    STRUCTURAL_COMMANDS = frozenset({
        r"\frac", r"\dfrac", r"\tfrac", r"\sqrt", r"\sum", r"\int",
        r"\iint", r"\iiint", r"\oint", r"\prod", r"\lim", r"\partial",
        r"\nabla", r"\det", r"\binom", r"\hat", r"\vec", r"\tilde",
        r"\overline", r"\underline", r"\overrightarrow", r"\mathcal",
        r"\mathbf", r"\mathrm", r"\mathbb", r"\infty", r"\sin",
        r"\cos", r"\tan", r"\log", r"\ln", r"\exp", r"\max", r"\min",
        r"\sup", r"\inf", r"\arg", r"\begin", r"\end", r"\left", r"\right",
        r"\text", r"\operatorname", r"\placeholder", r"\cdots", r"\vdots",
        r"\ddots", r"\because", r"\therefore", r"\blacksquare",
    })

    def highlight(self, latex: str) -> str:
        """Convert LaTeX source to syntax-highlighted HTML."""
        tokens = self._tokenize(latex)
        parts: list[str] = []
        for role, value in tokens:
            escaped = html.escape(value)
            if role == "frac":
                parts.append(f'<span class="latex-frac">{escaped}</span>')
            elif role == "structural":
                parts.append(f'<span class="latex-structural">{escaped}</span>')
            elif role == "operator":
                parts.append(f'<span class="latex-operator">{escaped}</span>')
            elif role == "delimiter":
                parts.append(f'<span class="latex-delimiter">{escaped}</span>')
            else:
                parts.append(escaped)
        return "".join(parts)

    def _tokenize(self, latex: str) -> list[tuple[str, str]]:
        """Lexical analysis: split LaTeX into semantic tokens."""
        tokens: list[tuple[str, str]] = []
        i = 0
        n = len(latex)

        while i < n:
            ch = latex[i]

            # ── Backslash command ──
            if ch == '\\' and i + 1 < n:
                # Collect \commandname
                j = i + 1
                if latex[j].isalpha():
                    while j < n and latex[j].isalpha():
                        j += 1
                    cmd = latex[i:j]
                    if cmd in self.FRAC_COMMANDS:
                        tokens.append(("frac", cmd))
                    elif cmd in self.STRUCTURAL_COMMANDS:
                        tokens.append(("structural", cmd))
                    else:
                        tokens.append(("structural", cmd))
                    i = j
                else:
                    # Single-char command like \, \  \{
                    tokens.append(("structural", latex[i:i+2]))
                    i += 2

            # ── Delimiters ──
            elif ch in '{}^_()[]|':
                tokens.append(("delimiter", ch))
                i += 1

            # ── Variable / operator ──
            elif ch.isalpha():
                tokens.append(("operator", ch))
                i += 1

            # ── Numbers ──
            elif ch.isdigit():
                # Collect full number
                j = i
                while j < n and (latex[j].isdigit() or latex[j] == '.'):
                    j += 1
                tokens.append(("operator", latex[i:j]))
                i = j

            # ── Operators ──
            elif ch in '=+<>-!':
                tokens.append(("operator", ch))
                i += 1

            # ── Whitespace ──
            elif ch in ' \t\n':
                tokens.append(("", ch))
                i += 1

            # ── Everything else ──
            else:
                tokens.append(("", ch))
                i += 1

        return tokens