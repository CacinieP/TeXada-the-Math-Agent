"""In-process KaTeX AST bridge backed by a reusable V8 context."""

from __future__ import annotations

import atexit
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from py_mini_racer import MiniRacer

# Structural depth safety budget. KaTeX's recursive parser, the semantic
# mapper, the tolerant fallback parser, and every recursive serializer
# (to_dict / fingerprint / tree weights / json.dumps) share this ceiling.
# A nesting depth above this budget can hang or crash the in-process V8 on
# some platforms, so it is checked before any bridge call.
MAX_NESTING_DEPTH = 100
# Consecutive V8 context failures before the bridge stays unavailable.
MAX_CONTEXT_REBUILDS = 3

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


def max_nesting_depth(latex: str) -> int:
    """Return the maximum ``{``/``[`` nesting depth, ignoring escaped chars.

    This is a cheap O(n) structural scan used as a pre-flight guard before
    any V8/KaTeX call. Braces and brackets are both counted because both can
    drive unbounded recursion in KaTeX's parser, the semantic mapper, and the
    tolerant fallback parser. Escaped delimiters (``\\{``, ``\\[``, ...) are
    skipped so balanced display-math or literal delimiters do not inflate the
    depth.
    """
    depth = 0
    max_depth = 0
    index = 0
    length = len(latex)
    while index < length:
        char = latex[index]
        if char == "\\":
            index += 2
            continue
        if char in "{[":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif char in "}]":
            if depth:
                depth -= 1
        index += 1
    return max_depth


class KaTeXASTParser:
    """Load the vendored KaTeX build once and expose its internal parse tree."""

    def __init__(self, javascript_path: Path | None = None):
        self.javascript_path = javascript_path or self._find_javascript()
        self._context: MiniRacer | None = None
        self._lock = threading.RLock()
        self._rebuild_count = 0
        self._permanently_failed = False

    def parse(self, latex: str) -> KaTeXParseResult:
        if max_nesting_depth(latex) > MAX_NESTING_DEPTH:
            return KaTeXParseResult(
                ok=False,
                error=(
                    f"maximum nesting depth exceeded "
                    f"(limit {MAX_NESTING_DEPTH})"
                ),
            )
        with self._lock:
            self._ensure_context()
            if self._context is None:
                return KaTeXParseResult(ok=False, error="KaTeX V8 context is unavailable")
            try:
                raw = self._context.call("texadaParseKaTeX", latex)
            except Exception as exc:
                self._note_context_failure(exc)
                return KaTeXParseResult(
                    ok=False,
                    error=f"KaTeX V8 context failed: {exc}",
                )
        data = json.loads(str(raw))
        return KaTeXParseResult(
            ok=bool(data.get("ok")),
            ast=data.get("ast") or [],
            error=str(data.get("error") or ""),
            version=str(data.get("version") or ""),
        )

    def render(self, latex: str) -> KaTeXRenderResult:
        """Render with the same vendored KaTeX context and macro policy."""
        if max_nesting_depth(latex) > MAX_NESTING_DEPTH:
            return KaTeXRenderResult(
                ok=False,
                error=(
                    f"maximum nesting depth exceeded "
                    f"(limit {MAX_NESTING_DEPTH})"
                ),
            )
        with self._lock:
            self._ensure_context()
            if self._context is None:
                return KaTeXRenderResult(
                    ok=False,
                    error="KaTeX V8 context is unavailable",
                )
            try:
                raw = self._context.call("texadaRenderKaTeX", latex)
            except Exception as exc:
                self._note_context_failure(exc)
                return KaTeXRenderResult(
                    ok=False,
                    error=f"KaTeX V8 context failed: {exc}",
                )
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
            try:
                context.close()
            except Exception:
                pass

    def _note_context_failure(self, exc: Exception) -> None:
        """Drop a failed V8 context so the next call rebuilds it.

        mini-racer destroys the isolate when the hard memory limit is hit;
        calling the dead context afterwards fails forever. Rebuild up to
        MAX_CONTEXT_REBUILDS times, then stay unavailable instead of
        rebuilding in a tight loop.
        """
        with self._lock:
            context = self._context
            self._context = None
            self._rebuild_count += 1
            if self._rebuild_count >= MAX_CONTEXT_REBUILDS:
                self._permanently_failed = True
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def _ensure_context(self) -> None:
        if self._context is not None or self._permanently_failed:
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


def _close_shared_parser() -> None:
    """Release V8 at interpreter exit so CLI/script/test processes exit cleanly.

    mini-racer keeps a non-daemon worker thread alive; without close() the
    process hangs until SIGTERM. The FastAPI lifespan also calls close(), and
    close() is idempotent, so double shutdown is harmless.
    """
    try:
        shared_katex_parser().close()
    except Exception:
        pass


atexit.register(_close_shared_parser)
