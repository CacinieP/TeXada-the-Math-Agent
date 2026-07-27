"""In-process KaTeX AST bridge backed by a reusable V8 context."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from py_mini_racer import MiniRacer

_WRAPPER = r"""
var texadaKaTeXOptions = {
  throwOnError: true,
  strict: "ignore",
  maxExpand: 1000,
  macros: {
    "\\placeholder": "\\square"
  }
};

function texadaParseKaTeX(latexStr) {
  try {
    var ast = katex.__parse(latexStr, texadaKaTeXOptions);
    return JSON.stringify({
      ok: true,
      version: katex.version || "unknown",
      ast: ast
    }, function(key, value) {
      if (key === "loc" && value) {
        return {start: value.start, end: value.end};
      }
      return value;
    });
  } catch (error) {
    return JSON.stringify({
      ok: false,
      version: katex.version || "unknown",
      error: String(error && error.message ? error.message : error)
    });
  }
}

function texadaRenderKaTeX(latexStr) {
  try {
    return JSON.stringify({
      ok: true,
      version: katex.version || "unknown",
      html: katex.renderToString(latexStr, Object.assign(
        {output: "htmlAndMathml"},
        texadaKaTeXOptions
      ))
    });
  } catch (error) {
    return JSON.stringify({
      ok: false,
      version: katex.version || "unknown",
      error: String(error && error.message ? error.message : error)
    });
  }
}
"""


@dataclass
class KaTeXParseResult:
    ok: bool
    ast: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    version: str = ""


@dataclass
class KaTeXRenderResult:
    ok: bool
    html: str = ""
    error: str = ""
    version: str = ""


class KaTeXASTParser:
    """Load the vendored KaTeX build once and expose its internal parse tree."""

    def __init__(self, javascript_path: Path | None = None):
        self.javascript_path = javascript_path or self._find_javascript()
        self._context: MiniRacer | None = None
        self._lock = threading.RLock()

    def parse(self, latex: str) -> KaTeXParseResult:
        with self._lock:
            self._ensure_context()
            if self._context is None:
                return KaTeXParseResult(ok=False, error="KaTeX V8 context is unavailable")
            raw = self._context.call("texadaParseKaTeX", latex)
        data = json.loads(str(raw))
        return KaTeXParseResult(
            ok=bool(data.get("ok")),
            ast=data.get("ast") or [],
            error=str(data.get("error") or ""),
            version=str(data.get("version") or ""),
        )

    def render(self, latex: str) -> KaTeXRenderResult:
        """Render with the same vendored KaTeX context and macro policy."""
        with self._lock:
            self._ensure_context()
            if self._context is None:
                return KaTeXRenderResult(
                    ok=False,
                    error="KaTeX V8 context is unavailable",
                )
            raw = self._context.call("texadaRenderKaTeX", latex)
        data = json.loads(str(raw))
        return KaTeXRenderResult(
            ok=bool(data.get("ok")),
            html=str(data.get("html") or ""),
            error=str(data.get("error") or ""),
            version=str(data.get("version") or ""),
        )

    def close(self) -> None:
        """Release V8 and its worker loop so the backend can exit cleanly."""
        with self._lock:
            context = self._context
            self._context = None
        if context is not None:
            context.close()

    def _ensure_context(self) -> None:
        if self._context is not None:
            return
        source = self.javascript_path.read_text(encoding="utf-8")
        # mini-racer binds a new context to the currently running asyncio loop.
        # SemanticParser is synchronous and is also called from FastAPI/pytest
        # async tasks, whose loops may later close. Constructing V8 on a short
        # plain worker thread makes mini-racer create its own durable loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            context = executor.submit(MiniRacer).result()
        context.set_soft_memory_limit(64 * 1024 * 1024)
        context.set_hard_memory_limit(128 * 1024 * 1024)
        context.eval("var window = this; var self = this;")
        context.eval(source)
        context.eval(_WRAPPER)
        self._context = context

    @staticmethod
    def _find_javascript() -> Path:
        candidates = [
            Path(__file__).resolve().parent / "vendor" / "katex.min.js",
            Path(__file__).resolve().parents[3]
            / "tauri-shell"
            / "src"
            / "vendor"
            / "katex"
            / "katex.min.js",
        ]
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            candidates.insert(
                0,
                Path(bundle_root) / "texada" / "semantic" / "vendor" / "katex.min.js",
            )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise RuntimeError("Vendored KaTeX JavaScript was not found")


@lru_cache(maxsize=1)
def shared_katex_parser() -> KaTeXASTParser:
    """Return the process-wide reusable V8/KaTeX parser."""
    return KaTeXASTParser()
