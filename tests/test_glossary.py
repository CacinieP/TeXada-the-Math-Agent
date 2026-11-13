"""Tests for the named-theorem glossary (issue #87)."""
from unittest.mock import AsyncMock

import pytest
import yaml

from texada.config import TeXadaConfig
from texada.core.glossary import ENTRIES, GlossaryEntry, lookup, normalise
from texada.core.router import InputRouter
from texada.core.validator import LaTeXValidator
from texada.types import Route


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_entry_is_valid_katex(entry):
    result = LaTeXValidator().validate(entry.latex)
    assert result.valid, f"{entry.id} is not valid KaTeX: {[e.error for e in result.errors]}"


def test_entries_are_traceable_and_unique():
    ids = [e.id for e in ENTRIES]
    assert len(ids) == len(set(ids))
    for entry in ENTRIES:
        assert entry.names, f"{entry.id} has no alias"
        assert entry.source, f"{entry.id} has no source"


def test_aliases_do_not_collide_across_entries():
    seen: dict[str, str] = {}
    for entry in ENTRIES:
        for name in entry.names:
            key = normalise(name)
            if key in seen and seen[key] != entry.id:
                raise AssertionError(f"alias {name!r} maps to {seen[key]} and {entry.id}")
            seen[key] = entry.id


def test_case_insensitive_aliases_for_english():
    assert lookup("Bayes").id == "bayes"
    assert lookup("STOKES").id == "stokes"


def test_real_world_corpus_named_formulas_all_resolve():
    entries = yaml.safe_load(
        (__import__("pathlib").Path(__file__).resolve().parents[1]
         / "eval" / "real_world_set.yaml").read_text(encoding="utf-8")
    )["entries"]
    named = [e["input"] for e in entries if e["category"] == "named-formula"]
    assert named, "corpus has no named-formula entries"
    misses = [text for text in named if lookup(text) is None]
    assert misses == [], f"glossary misses {misses}"


@pytest.mark.parametrize("text", [
    "二重积分",          # not a theorem name
    "矩阵",
    "极限",
    "格林公式和斯托克斯公式的区别",   # two names in one sentence
    "求格林公式",        # wrapped in a verb → model decides
    "泰勒展开式",        # qualified name, not the bare theorem
    "欧拉方法",          # different concept sharing a name
    "高斯消元",
    "贝叶斯网络",
    "",
])
def test_parameters_and_near_misses_do_not_resolve(text):
    assert lookup(text) is None


@pytest.mark.parametrize("text,expect", [
    ("格林公式", "green"),
    ("请帮我排版格林公式", "green"),
    ("格林公式（L 为逆时针闭曲线）", "green"),
    ("罗尔定理", "rolle"),
    ("华里士公式", "wallis"),
    ("点火公式", "wallis"),
])
def test_name_forms_that_should_resolve(text, expect):
    entry = lookup(text)
    assert entry is not None and entry.id == expect


# ── router 集成 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_serves_glossary_without_touching_the_model(tmp_path):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(side_effect=AssertionError("no inference"))
    router.model.generate_latex = AsyncMock(side_effect=AssertionError("no inference"))

    result = await router.process_text("格林公式", route_override=Route.NL2LATEX)

    assert result.source.value == "template"
    assert result.tokens_used == 0
    assert result.valid
    assert result.fix_log == ["glossary:green"]
    assert r"\oint_L" in result.latex
    router.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_falls_back_to_the_model_on_a_miss(tmp_path):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(return_value=True)
    called = []

    async def fake_generate(preprocessed, intent, **_):
        called.append(intent)
        return "x^2"

    router.model.generate_latex = fake_generate

    result = await router.process_text("x 的平方", route_override=Route.NL2LATEX)

    assert called, "model should have been asked"
    assert result.source.value == "model"
    assert result.latex == "x^2"


@pytest.mark.asyncio
async def test_router_skips_glossary_when_context_is_supplied(tmp_path):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(return_value=True)
    called = []

    async def fake_generate(preprocessed, intent, **_):
        called.append(preprocessed)
        return "x"

    router.model.generate_latex = fake_generate

    await router.process_text(
        "格林公式", context="上一题讨论的是高斯公式", route_override=Route.NL2LATEX
    )

    assert called, "context requests must keep going to the model"


@pytest.mark.asyncio
async def test_router_ignores_a_glossary_entry_that_fails_validation(tmp_path, monkeypatch):
    router = InputRouter(TeXadaConfig(data_dir=tmp_path))
    router.backend.ensure_ready = AsyncMock(return_value=True)

    async def fake_generate(preprocessed, intent, **_):
        return "x^2"

    router.model.generate_latex = fake_generate
    monkeypatch.setattr(
        "texada.core.router.lookup_glossary_entry",
        lambda _text: GlossaryEntry(id="broken", names=("坏",), latex=r"\frac{1}{"),
    )

    result = await router.process_text("坏", route_override=Route.NL2LATEX)

    assert result.source.value == "model"
    assert result.latex == "x^2"