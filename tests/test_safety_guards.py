"""Regression tests for the safety guards that prevent hangs and crashes.

These tests lock in the fixes for three verified failure modes:

1. Deeply nested input (a legal 3151-character ``\\frac`` chain) previously
   crashed or hung the whole process — inside the in-process V8/KaTeX bridge,
   in the tolerant fallback parser (uncaught RecursionError), and in the
   recursive serializers (C-stack overflow via json.dumps).
2. Oversized ``semantic_diff`` inputs ran an O(m·n) DP with no guard
   (n=1200 → ~65s, n=2000 → SIGBUS).
3. The SymbolEngine sequential re.sub loop double-translated its own output
   ("argmax" → ``\\arg\\\\max``, "limsup" → ``\\lim\\sup``).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from texada.config import TeXadaConfig
from texada.core.symbols import SymbolEngine
from texada.semantic import SemanticDiffer, SemanticParser
from texada.semantic.katex import (
    MAX_NESTING_DEPTH,
    max_nesting_depth,
    shared_katex_parser,
)
from texada.semantic.model import (
    MAX_SEMANTIC_DEPTH,
    SemanticDepthError,
    SemanticUnit,
)
from texada.tools import TeXToolset, ToolRouter

# ── SymbolEngine: single-pass longest match ──

def test_symbols_no_double_translation_of_replacements():
    eng = SymbolEngine()
    assert eng.pre_translate("argmax f(x)") == r"\arg\max f(x)"
    assert eng.pre_translate("limsup x") == r"\limsup x"
    assert eng.pre_translate("liminf x") == r"\liminf x"


def test_symbols_compound_words_not_corrupted():
    eng = SymbolEngine()
    assert eng.pre_translate("向量空间") == "向量空间"
    assert eng.pre_translate("概率空间") == "概率空间"
    assert eng.pre_translate("概率密度函数") == "概率密度函数"


def test_symbols_already_escaped_latex_untouched():
    eng = SymbolEngine()
    assert eng.pre_translate(r"\sin x") == r"\sin x"
    assert eng.pre_translate(r"\limsup x") == r"\limsup x"


def test_symbols_english_word_boundaries():
    eng = SymbolEngine()
    assert eng.pre_translate("sine") == "sine"
    assert eng.pre_translate("sin x") == r"\sin x"
    assert eng.pre_translate("ln 2") == r"\ln 2"


def test_symbols_existing_contract_still_holds():
    eng = SymbolEngine()
    assert eng.pre_translate("三重积分") == r"\iiint"
    assert eng.pre_translate("二重积分 f(x,y) 在区域 D 上") == (
        r"\iint f(x,y) 在区域 D 上"
    )
    assert eng.pre_translate("导数定义") == "导数定义"
    assert eng.pre_translate("\\iint f(x,y)") == "\\iint f(x,y)"
    assert "\\alpha" in eng.pre_translate("阿尔法贝塔")


# ── Nesting depth guard ──

def test_max_nesting_depth_scanner():
    assert max_nesting_depth(r"a+b") == 0
    assert max_nesting_depth(r"\frac{a}{b}") == 1
    assert max_nesting_depth(r"\{") == 0
    assert max_nesting_depth(r"\[x\]") == 0
    assert max_nesting_depth(r"\left[ x \right]") == 1
    assert max_nesting_depth(r"\frac{\frac{x}{y}}{z}") == 2


def test_nesting_guard_returns_controlled_document():
    parser = SemanticParser()
    depth = MAX_NESTING_DEPTH + 50
    deep = r"\frac{" * depth + "x" + "}" * depth
    doc = parser.parse(deep)
    assert doc.parser_backend == "depth-guard"
    assert doc.diagnostics
    # Serialization and fingerprinting must not crash or raise.
    doc.to_dict()
    doc.root.fingerprint()
    # ...and parsing again is still healthy afterwards.
    normal = parser.parse(r"\frac{a}{b}")
    assert normal.parser_backend.startswith("katex-")


def test_bridge_rejects_deep_input_before_v8_call(monkeypatch):
    import texada.semantic.katex as katex_mod

    called = {"n": 0}

    class FakeContext:
        def set_soft_memory_limit(self, *args): ...
        def set_hard_memory_limit(self, *args): ...
        def eval(self, *args): ...
        def close(self): ...

        def call(self, *args):
            called["n"] += 1
            return '{"ok": true, "ast": [], "version": "0.17.0"}'

    monkeypatch.setattr(katex_mod, "MiniRacer", FakeContext)
    parser = katex_mod.KaTeXASTParser(javascript_path=Path("dummy.js"))
    deep = r"\frac{" * (MAX_NESTING_DEPTH + 5) + "x" + "}" * (MAX_NESTING_DEPTH + 5)
    result = parser.parse(deep)
    assert result.ok is False
    assert "nesting depth" in result.error
    assert called["n"] == 0  # V8 was never touched


def test_v8_context_self_heals_after_failure(monkeypatch, tmp_path):
    import texada.semantic.katex as katex_mod

    state = {"calls": 0, "instances": []}

    class FlakyContext:
        def __init__(self):
            self.closed = False
            state["instances"].append(self)

        def set_soft_memory_limit(self, *args): ...
        def set_hard_memory_limit(self, *args): ...
        def eval(self, *args): ...

        def call(self, *args):
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("simulated V8 OOM")
            return '{"ok": true, "ast": [], "version": "0.17.0"}'

        def close(self):
            self.closed = True

    monkeypatch.setattr(katex_mod, "MiniRacer", FlakyContext)
    js_path = tmp_path / "dummy.js"
    js_path.write_text("// dummy")

    parser = katex_mod.KaTeXASTParser(javascript_path=js_path)

    first = parser.parse("x")
    assert first.ok is False
    assert "failed" in first.error
    assert state["instances"][0].closed is True

    second = parser.parse("x")
    assert second.ok is True  # context was rebuilt
    assert len(state["instances"]) == 2


def test_v8_context_gives_up_after_rebuild_limit(monkeypatch, tmp_path):
    import texada.semantic.katex as katex_mod

    state = {"calls": 0}

    class AlwaysBrokenContext:
        def set_soft_memory_limit(self, *args): ...
        def set_hard_memory_limit(self, *args): ...
        def eval(self, *args): ...

        def call(self, *args):
            state["calls"] += 1
            raise RuntimeError("always fails")

        def close(self): ...

    monkeypatch.setattr(katex_mod, "MiniRacer", AlwaysBrokenContext)
    js_path = tmp_path / "dummy.js"
    js_path.write_text("// dummy")

    parser = katex_mod.KaTeXASTParser(javascript_path=js_path)

    results = [parser.parse("x") for _ in range(6)]
    assert all(not r.ok for r in results)
    # Rebuild attempts are capped; later calls do not keep rebuilding.
    assert state["calls"] == katex_mod.MAX_CONTEXT_REBUILDS


def test_deep_nesting_via_router_is_controlled():
    async def run():
        router = ToolRouter(TeXToolset(TeXadaConfig()))
        deep = r"\frac{" * 450 + "x" + "}" * 450
        obs = await router.execute("compile_tex", {"latex": deep})
        assert obs.ok
        assert obs.output["valid"] is False
        assert obs.output["semantic_document"]["parser_backend"] == "depth-guard"
    asyncio.run(run())


def test_to_dict_and_fingerprint_depth_budget():
    unit = SemanticUnit(kind="group")
    current = unit
    for _ in range(MAX_SEMANTIC_DEPTH + 5):
        child = SemanticUnit(kind="group")
        current.children.append(child)
        current = child
    with pytest.raises(SemanticDepthError):
        unit.to_dict()
    with pytest.raises(SemanticDepthError):
        unit.fingerprint()


# ── Diff scale guard ──

def test_diff_degrades_fast_on_oversized_input():
    differ = SemanticDiffer(SemanticParser())
    n = 1200  # previously ~65s, n=2000 previously SIGBUS
    a = "a" * n
    b = "a" * (n - 2) + "xy"
    start = time.monotonic()
    result = differ.diff(a, b)
    elapsed = time.monotonic() - start
    assert result.degraded is True
    assert elapsed < 5.0
    payload = result.to_dict()
    assert payload["degraded"] is True


def test_diff_stays_exact_below_budget():
    differ = SemanticDiffer(SemanticParser())
    result = differ.diff("a b c", "a b c")
    assert result.degraded is False
    assert result.equivalent is True
    assert differ.diff(r"\frac{a}{b}", r"\frac{a}{b}").equivalent is True


def test_diff_small_change_still_reported_when_degraded():
    differ = SemanticDiffer(SemanticParser())
    n = 700  # above the DP budget, below KaTeX limits
    result = differ.diff("a" * n, "a" * (n - 1) + "z")
    assert result.degraded is True
    assert result.to_dict()["change_count"] >= 1


# ── Tool execution timeout ──

def test_tool_timeout_returns_observation():
    async def run():
        router = ToolRouter(TeXToolset(TeXadaConfig()), timeout_seconds=0.2)

        def slow(latex):
            time.sleep(5)
            return {"latex": latex}

        router._handlers["parse_tex"] = slow
        start = time.monotonic()
        obs = await router.execute("parse_tex", {"latex": "x"})
        assert obs.ok is False
        assert "timed out" in obs.error
        assert time.monotonic() - start < 3.0
    asyncio.run(run())


def test_tool_router_survives_timeout():
    async def run():
        router = ToolRouter(TeXToolset(TeXadaConfig()), timeout_seconds=0.2)

        def slow(latex):
            time.sleep(5)
            return {"latex": latex}

        router._handlers["parse_tex"] = slow
        await router.execute("parse_tex", {"latex": "x"})
        # The real handler is still reachable via the toolset-backed map.
        router._handlers["parse_tex"] = router.toolset.parse_tex
        obs = await router.execute("parse_tex", {"latex": r"\frac{a}{b}"})
        assert obs.ok
        assert obs.output["semantic_document"]["parser_backend"].startswith("katex-")
    asyncio.run(run())


# ── Attack chain: oversized malformed input through repair_tex ──

def test_oversized_malformed_input_through_repair_tex_is_fast():
    async def run():
        router = ToolRouter(TeXToolset(TeXadaConfig()))
        bad = r"\frac{" * 200 + "x" + "}" * 100
        bad = (bad + " " * 1000)[:4000]
        start = time.monotonic()
        obs = await router.execute("repair_tex", {"latex": bad})
        elapsed = time.monotonic() - start
        assert obs.ok
        assert elapsed < 5.0
    asyncio.run(run())


def test_shared_parser_close_is_idempotent():
    parser = shared_katex_parser()
    parser.close()
    parser.close()
    assert parser._context is None
