"""Test the deterministic arXiv import path — zero model calls.

The network is simulated with ``httpx.MockTransport`` and synthetic
tarballs; no test touches arxiv.org. Golden assertions pin extraction
behavior: math delimiters, labels, sections, macro collection, and the
escapes (``\\$``, ``\\\\[2pt]``) that must never open math.
"""
from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from texada.core import arxiv

MAIN_TEX = r"""\documentclass{article}
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}
\DeclareMathOperator{\rank}{rank}
\title{Sample Paper Title}
\begin{document}
\input{ch1}
\end{document}
"""

CH1_TEX = r"""\section{Results}
Consider $x + y$ inline math and display:
$$E = mc^2$$
An escaped price is \$5 and 100\% done.
\begin{equation}
\label{eq:main}
\int_0^1 x^2 \, dx = \frac{1}{3}
\end{equation}
\begin{align*}
a &= b + c \\
d &= e
\end{align*}
A linebreak with spacing \\[2pt] then \[ z = w \] display.
% a commented formula $\shouldnotappear$
\subsection{Details}
\[ \R^n \quad \norm{v} \quad \rank(M) \]
\begin{verbatim}
$notmath$
\end{verbatim}
End.
"""


def make_files() -> dict[str, str]:
    return {"main.tex": MAIN_TEX, "ch1.tex": CH1_TEX}


def make_tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def mock_transport(files: dict[str, str], calls: dict | None = None):
    payload = make_tarball(files)

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls["n"] = calls.get("n", 0) + 1
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/x-e-print-tar"},
        )

    return httpx.MockTransport(handler)


# ── reference parsing ──

@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("2403.12345", "2403.12345"),
        (" 2403.12345v2 ", "2403.12345v2"),
        ("hep-ph/9901001", "hep-ph/9901001"),
        ("https://arxiv.org/abs/2403.12345", "2403.12345"),
        ("http://arxiv.org/pdf/2403.12345v3", "2403.12345v3"),
        ("https://export.arxiv.org/abs/hep-ph/9901001", "hep-ph/9901001"),
        ("arxiv.org/e-print/2403.12345/", "2403.12345"),
    ],
)
def test_parse_arxiv_ref_accepts_ids_and_urls(ref, expected):
    assert arxiv.parse_arxiv_ref(ref) == expected


@pytest.mark.parametrize("ref", ["", "not a ref", "https://example.com/x", "12345"])
def test_parse_arxiv_ref_rejects_garbage(ref):
    with pytest.raises(arxiv.ArxivRefError):
        arxiv.parse_arxiv_ref(ref)


# ── flattening ──

def test_strip_comments_keeps_lines_and_escapes():
    tex = "a % gone\nb\n100\\% done\n"
    out = arxiv.strip_comments(tex)
    assert "\\% done" in out
    assert "gone" not in out
    assert out.count("\n") == tex.count("\n")


def test_flatten_source_merges_inputs_and_picks_main():
    flattened = arxiv.flatten_source(make_files())
    assert "\\documentclass" in flattened
    assert "\\section{Results}" in flattened  # ch1.tex was inlined
    assert "shouldnotappear" not in flattened  # comments are stripped
    assert arxiv.strip_comments(flattened) == flattened  # already stripped


def test_flatten_source_requires_tex():
    with pytest.raises(arxiv.ArxivSourceError):
        arxiv.flatten_source({"readme.md": "no tex here"})


# ── macros ──

def test_extract_macros_variants():
    macros = arxiv.extract_macros(MAIN_TEX)
    assert macros[r"\R"] == r"\mathbb{R}"
    assert macros[r"\norm"] == r"\left\lVert #1 \right\rVert"
    assert macros[r"\rank"] == r"\operatorname{rank}"


def test_extract_macros_def_with_params():
    tex = r"\def\foo#1#2{#1 + #2}"
    macros = arxiv.extract_macros(tex)
    assert macros[r"\foo"] == r"#1 + #2"


def test_used_macros_is_transitive():
    macros = {r"\A": r"\B + 1", r"\B": "2", r"\C": "unused"}
    needed = arxiv.used_macros(r"x + \A", macros)
    assert needed == {r"\A": r"\B + 1", r"\B": "2"}


# ── formula extraction (golden) ──

def test_extract_formulas_golden():
    flattened = arxiv.flatten_source(make_files())
    formulas = arxiv.extract_formulas(flattened)

    by_env = [f for f in formulas if f.env != "inline"]
    latexes = [f.latex for f in formulas]

    # the six real formulas, in document order
    assert latexes == [
        "x + y",
        "E = mc^2",
        r"\int_0^1 x^2 \, dx = \frac{1}{3}",
        "a &= b + c \\\\\nd &= e",
        "z = w",
        r"\R^n \quad \norm{v} \quad \rank(M)",
    ]

    main = formulas[2]
    assert main.env == "equation"
    assert main.display is True
    assert main.label == "eq:main"
    assert "\\label" not in main.latex  # lifted out for KaTeX
    assert main.section == "Results"

    details = formulas[5]
    assert details.env == "display"
    assert details.section == "Details"
    assert details.label is None

    # context is populated and does not leak math delimiters of the formula
    assert all(f.context == "" or not f.context.strip().startswith("$") for f in formulas)

    # never extracted: escaped \$, \\[2pt], commented math, verbatim
    assert "$shouldnotappear" not in " ".join(latexes)
    assert "notmath" not in " ".join(latexes)
    assert all("2pt" not in f.latex for f in formulas)

    # line numbers refer to the flattened text and stay sorted
    lines = [f.line for f in formulas]
    assert lines == sorted(lines)
    assert all(line >= 1 for line in lines)

    # display flags
    assert [f.display for f in formulas] == [
        False, True, True, True, True, True,
    ]
    assert by_env  # equation/align*/display environments were captured


def test_extract_title():
    flattened = arxiv.flatten_source(make_files())
    assert arxiv.extract_title(flattened) == "Sample Paper Title"


# ── fetching (mocked network) ──

async def test_fetch_and_extract_then_cache_hit(tmp_path):
    calls: dict = {}
    transport = mock_transport(make_files(), calls)
    async with httpx.AsyncClient(transport=transport) as client:
        paper = await arxiv.fetch_and_extract(
            "2403.12345", cache_root=tmp_path, client=client
        )
        assert paper.cached is False
        assert paper.title == "Sample Paper Title"
        assert len(paper.formulas) == 6
        assert calls["n"] == 1

        paper2 = await arxiv.fetch_and_extract(
            "2403.12345", cache_root=tmp_path, client=client
        )
        assert paper2.cached is True
        assert [f.latex for f in paper2.formulas] == [
            f.latex for f in paper.formulas
        ]
        assert calls["n"] == 1  # served from cache, transport untouched


async def test_fetch_pdf_only_is_a_hard_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4 fake",
            headers={"content-type": "application/pdf"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(arxiv.ArxivNoSourceError):
            await arxiv.fetch_and_extract(
                "2403.99999", cache_root=tmp_path, client=client
            )


async def test_fetch_unknown_paper_maps_to_not_found(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(arxiv.ArxivNotFoundError):
            await arxiv.fetch_and_extract(
                "9999.99999", cache_root=tmp_path, client=client
            )


# ── rendering with the accompanying macro pack ──

def test_katex_render_uses_imported_macros():
    from texada.semantic.katex import shared_katex_parser

    parser = shared_katex_parser()
    bare = parser.render(r"\norm{v}")
    assert bare.ok is False  # unknown macro without the paper's pack

    with_pack = parser.render(
        r"\norm{v}", {r"\norm": r"\left\lVert #1 \right\rVert"}
    )
    assert with_pack.ok is True
    assert "katex" in with_pack.html

    operator = parser.render(
        r"\rank(M)", {r"\rank": r"\operatorname{rank}"}
    )
    assert operator.ok is True


def test_render_engine_accepts_macros(tmp_path):
    from texada.config import TeXadaConfig
    from texada.render.engine import RenderEngine

    engine = RenderEngine(TeXadaConfig(data_dir=tmp_path))
    result = engine.render(
        r"\R^n", macros={r"\R": r"\mathbb{R}"}
    )
    assert result.katex_html is not None
    assert "katex-fallback" not in result.katex_html


# ── API endpoints ──

async def test_import_endpoints_end_to_end(tmp_path):
    from fastapi.testclient import TestClient

    from texada.api import create_app
    from texada.config import TeXadaConfig

    calls: dict = {}
    async with httpx.AsyncClient(
        transport=mock_transport(make_files(), calls)
    ) as client:
        await arxiv.fetch_and_extract(
            "2403.12345",
            cache_root=tmp_path / "cache" / "arxiv",
            client=client,
        )
    assert calls["n"] == 1

    config = TeXadaConfig(data_dir=tmp_path)
    app = create_app(config)
    with TestClient(app) as client:
        # bad reference → 400
        bad = client.post("/api/import/arxiv", json={"ref": "not-a-ref"})
        assert bad.status_code == 400

        # import from cache (no network in the endpoint path)
        response = client.post(
            "/api/import/arxiv",
            json={"ref": "https://arxiv.org/abs/2403.12345"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["arxiv_id"] == "2403.12345"
        assert body["cached"] is True
        assert body["title"] == "Sample Paper Title"
        assert body["formula_count"] == 6
        assert calls["n"] == 1

        # select the labeled equation: valid + rendered, zero tokens
        idx = next(
            i for i, f in enumerate(body["formulas"]) if f["label"] == "eq:main"
        )
        selected = client.post(
            "/api/import/select",
            json={"arxiv_id": "2403.12345", "index": idx},
        )
        assert selected.status_code == 200
        sel = selected.json()
        assert sel["valid"] is True
        assert sel["intent"] == "import"
        assert sel["tokens_used"] == 0
        assert sel["katex_html"] and "katex-fallback" not in sel["katex_html"]

        # select the macro-dependent formula: pack is applied on render
        macro_idx = next(
            i
            for i, f in enumerate(body["formulas"])
            if r"\R^n" in f["latex"]
        )
        macro_sel = client.post(
            "/api/import/select",
            json={"arxiv_id": "2403.12345", "index": macro_idx},
        )
        assert macro_sel.status_code == 200
        assert "katex-fallback" not in macro_sel.json()["katex_html"]

        # out-of-range and un-imported → 404
        assert client.post(
            "/api/import/select",
            json={"arxiv_id": "2403.12345", "index": 999},
        ).status_code == 404
        assert client.post(
            "/api/import/select",
            json={"arxiv_id": "1111.22222", "index": 0},
        ).status_code == 404
