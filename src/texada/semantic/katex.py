"""In-process KaTeX AST bridge backed by a reusable V8 context."""

from __future__ import annotations

import atexit
import json
import sys
import threading
import traceback
from concurrent.futures import Future
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from queue import Queue
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
    """Keep the complete native context lifecycle on one plain owner thread.

    MiniRacer 0.14 captures a running asyncio loop at construction, and its
    close() exits the context manager that owns that loop and native isolate.
    A temporary constructor thread is therefore not a lifecycle boundary:
    synchronous callers, ASGI tasks and lifespan shutdown can all run elsewhere.
    No MiniRacer object or JS value crosses our owner queue; callers receive
    only JSON strings. See https://bpcreech.com/PyMiniRacer/ and its close API.
    """

    def __init__(self, javascript_path: Path | None = None):
        self.javascript_path = javascript_path or self._find_javascript()
        self._context: MiniRacer | None = None
        self._lock = threading.RLock()
        self._owner: threading.Thread | None = None
        self._tasks: Queue | None = None
        self._rebuild_count = 0
        self._permanently_failed = False

    @staticmethod
    def _serve(tasks: Queue) -> None:
        # Do not retain a bound parser method while idle: a non-shared parser
        # must be collectable, so its __del__ can close the native resources.
        while (item := tasks.get()) is not None:
            operation, future = item
            try:
                value, failure = operation(), None
            except BaseException as exc:
                # Constructor failures can leave a partially initialized
                # MiniRacer alive in an exception frame. Passing that exception
                # through Future would make caller-side GC release native V8.
                # Retain only plain error data, and discard all original frames
                # on this owner before waking the caller.
                value, failure = None, KaTeXASTParser._owner_failure(exc)
            finally:
                del item, operation
            future.set_result((value, failure))
            del future, value, failure

    @staticmethod
    def _owner_failure(exc: BaseException) -> tuple[str, str, int | str | None]:
        try:
            message = str(exc)
        except BaseException:
            message = "KaTeX owner operation failed"
        kind, code = "error", None
        if isinstance(exc, KeyboardInterrupt):
            kind = "interrupt"
        elif isinstance(exc, SystemExit):
            kind = "exit"
            code = exc.code if type(exc.code) in (int, str, type(None)) else message
        elif isinstance(exc, GeneratorExit):
            kind = "generator_exit"
        # Chained failures may retain the same partial constructor in another
        # traceback. Break every chain and clear its frames while still here.
        pending, seen = [exc], set()
        while pending:
            error = pending.pop()
            if id(error) in seen:
                continue
            seen.add(id(error))
            pending.extend(link for link in (error.__cause__, error.__context__)
                           if link is not None)
            frames = error.__traceback__
            error.__traceback__ = error.__cause__ = error.__context__ = None
            if frames is not None:
                traceback.clear_frames(frames)
        return kind, message, code

    def _on_owner(self, operation):
        """Run a synchronous operation while the caller holds ``_lock``."""
        if self._owner is None:
            self._tasks = Queue()
            self._owner = threading.Thread(
                target=self._serve, args=(self._tasks,),
                name="texada-katex-owner", daemon=True,
            )
            self._owner.start()
        if threading.current_thread() is self._owner:
            return operation()
        future = Future()
        self._tasks.put((operation, future))
        value, failure = future.result()
        if failure is None:
            return value
        kind, message, code = failure
        if kind == "interrupt":
            raise KeyboardInterrupt(message)
        if kind == "exit":
            raise SystemExit(code)
        if kind == "generator_exit":
            raise GeneratorExit(message)
        raise RuntimeError(message)

    def _call(self, function: str, latex: str) -> str | None:
        """Create, call, and recover a context exclusively on its owner."""
        self._ensure_context()
        if self._context is None:
            return None
        try:
            return str(self._context.call(function, latex))
        except BaseException:
            self._note_context_failure()
            raise

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
            try:
                raw = self._on_owner(lambda: self._call("texadaParseKaTeX", latex))
            except Exception as exc:
                return KaTeXParseResult(
                    ok=False,
                    error=f"KaTeX V8 context failed: {exc}",
                )
        if raw is None:
            return KaTeXParseResult(ok=False, error="KaTeX V8 context is unavailable")
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
            try:
                raw = self._on_owner(lambda: self._call("texadaRenderKaTeX", latex))
            except Exception as exc:
                return KaTeXRenderResult(
                    ok=False,
                    error=f"KaTeX V8 context failed: {exc}",
                )
        if raw is None:
            return KaTeXRenderResult(ok=False, error="KaTeX V8 context is unavailable")
        data = json.loads(str(raw))
        return KaTeXRenderResult(
            ok=bool(data.get("ok")),
            html=str(data.get("html") or ""),
            error=str(data.get("error") or ""),
            version=str(data.get("version") or ""),
        )

    def close(self) -> None:
        """Close and join the owner before another caller may reopen V8."""
        with self._lock:
            owner, tasks = self._owner, self._tasks
            if owner is None:
                return
            try:
                self._on_owner(self._close_context)
            finally:
                tasks.put(None)
                if threading.current_thread() is not owner:
                    owner.join()
                self._owner = self._tasks = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _close_context(self) -> None:
        context, self._context = self._context, None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def _note_context_failure(self) -> None:
        """Drop a failed V8 context so the next call rebuilds it.

        mini-racer destroys the isolate when the hard memory limit is hit;
        calling the dead context afterwards fails forever. Rebuild up to
        MAX_CONTEXT_REBUILDS times, then stay unavailable instead of
        rebuilding in a tight loop.
        """
        self._close_context()
        self._rebuild_count += 1
        if self._rebuild_count >= MAX_CONTEXT_REBUILDS:
            self._permanently_failed = True

    def _ensure_context(self) -> None:
        if self._context is not None or self._permanently_failed:
            return
        source = self.javascript_path.read_text(encoding="utf-8")
        context = MiniRacer()
        try:
            context.set_soft_memory_limit(64 * 1024 * 1024)
            context.set_hard_memory_limit(128 * 1024 * 1024)
            context.eval("var window = this; var self = this;")
            context.eval(source)
            context.eval(_WRAPPER)
        except BaseException:
            context.close()
            raise
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

    The parser owns its queue thread independently of caller event loops and
    executor shutdown hooks. The FastAPI lifespan also calls close(); repeated
    shutdown is harmless, and a later lifespan can create a new owner.
    """
    try:
        shared_katex_parser().close()
    except Exception:
        pass


atexit.register(_close_shared_parser)
