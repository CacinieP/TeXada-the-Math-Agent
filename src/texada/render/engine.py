"""Render Engine — dual mode: KaTeX visual + pure LaTeX syntax highlight."""
from __future__ import annotations

import html
import subprocess

from texada.config import TeXadaConfig
from texada.render.highlighter import LaTeXHighlighter
from texada.types import RenderMode, RenderResult


class RenderEngine:
    """Dual render engine — ⌘K switches mode instantly, no model call."""

    def __init__(self, config: TeXadaConfig):
        self.mode = RenderMode(config.default_render_mode)
        self.delimiter = config.delimiter
        self.highlighter = LaTeXHighlighter()
        self._last_latex: str = ""

    # Delimiter pairs: open → close
    DELIMITER_PAIRS: dict[str, tuple[str, str]] = {
        "$$": ("$$", "$$"),
        "$": ("$", "$"),
        "\\[": ("\\[", "\\]"),
        "\\(": ("\\(", "\\)"),
    }

    def render(self, latex: str, *, mode_override: RenderMode | None = None) -> RenderResult:
        """Render LaTeX in current mode (or a per-request override)."""
        self._last_latex = latex  # Cache for ⌘K switch
        mode = mode_override or self.mode

        if mode == RenderMode.KATEX:
            katex_html = self._render_katex(latex)
            open_delim, close_delim = self.DELIMITER_PAIRS.get(
                self.delimiter, (self.delimiter, self.delimiter)
            )
            copy_text = f"{open_delim}{latex}{close_delim}"
            return RenderResult(
                latex=latex,
                katex_html=katex_html,
                copy_text=copy_text,
                mode=RenderMode.KATEX,
            )
        else:
            highlighted = self.highlighter.highlight(latex)
            copy_text = latex  # Bare LaTeX, no delimiters
            return RenderResult(
                latex=latex,
                latex_highlighted=highlighted,
                copy_text=copy_text,
                mode=RenderMode.LATEX,
            )

    def switch_mode(self, mode: str) -> RenderResult:
        """⌘K — re-render cached LaTeX in new mode, zero model call."""
        self.mode = RenderMode(mode)
        return self.render(self._last_latex)

    def _render_katex(self, latex: str) -> str:
        """KaTeX rendering via npx subprocess."""
        try:
            result = subprocess.run(
                ["npx", "katex", "-f", "tex"],
                input=latex, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout
            return f"<span class='katex-error'>KaTeX error: {html.escape(result.stderr[:100])}</span>"
        except FileNotFoundError:
            return f"<span class='katex-error'>npx katex not available</span>"
        except subprocess.TimeoutExpired:
            return f"<span class='katex-error'>KaTeX timeout</span>"