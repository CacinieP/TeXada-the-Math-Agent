"""Deterministic arXiv LaTeX source ingestion — the zero-model input path.

The paper's own LaTeX source is the ground truth, so acquisition,
flattening, math extraction, and macro collection are plain deterministic
code. A selected formula enters the shared runtime as a candidate and is
verified by the same compile/render tools as NL, OCR, and completion
candidates. PDF sources are refused rather than OCR-degraded because PDF
re-encoding is exactly the math-corruption this path exists to avoid.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ARXIV_EPRINT_URL = "https://arxiv.org/e-print/"
MAX_SOURCE_BYTES = 64 * 1024 * 1024  # download cap, matches arXiv's hard limit
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000
MAX_FORMULA_CHARS = 4_000  # compile guard budget, see nesting-depth limits
MAX_MACRO_COUNT = 500
MAX_MACRO_BODY_CHARS = 2_000
CONTEXT_CHARS = 160

# Math environments (starred variants included by stripping the star).
_MATH_ENVIRONMENTS = frozenset(
    {
        "equation",
        "gather",
        "multline",
        "eqnarray",
        "align",
        "alignat",
        "flalign",
        "math",
        "displaymath",
        "dmath",
    }
)

# Environments whose contents must never be scanned for math.
_VERBATIM_ENVIRONMENTS = frozenset(
    {"verbatim", "verbatim*", "lstlisting", "minted", "alltt"}
)

_LABEL_RE = re.compile(r"\\label\{([^{}]*)\}")
_SECTION_RE = re.compile(
    r"\\(?P<level>chapter|section|subsection)\*?\s*\{"
    r"(?P<title>[^{}]*)\}"
)
_TITLE_RE = re.compile(r"\\title\s*(?:\[[^\]]*\])?\s*\{")
_BEGIN_RE = re.compile(r"\\begin\s*\{([^{}]+)\}")
_MACRO_DEF_RE = re.compile(
    r"\\(?:re)?newcommand\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
    r"(?:\s*\[(\d)\])?\s*\{"
    r"|\\def\s*\\([A-Za-z@]+)(?:#[0-9])*\s*\{"
    r"|\\DeclareMathOperator\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*\{"
)


class ArxivRefError(ValueError):
    """The user-supplied reference is not an arXiv ID or arXiv URL."""


class ArxivSourceError(RuntimeError):
    """The source could not be fetched, unpacked, or contains no LaTeX."""


class ArxivNotFoundError(ArxivSourceError):
    """arXiv has no paper with the requested ID."""


class ArxivNoSourceError(ArxivSourceError):
    """The paper exists but exposes no LaTeX source (PDF only)."""


@dataclass(frozen=True)
class ExtractedFormula:
    """One math fragment lifted from the flattened paper text."""

    index: int
    latex: str
    env: str  # "inline", "display", or the environment name (e.g. "align")
    display: bool
    line: int
    section: str | None
    label: str | None
    context: str


@dataclass
class ArxivPaper:
    """Everything the import UI needs after one fetch."""

    arxiv_id: str
    title: str | None
    cached: bool
    flattened: str
    formulas: list[ExtractedFormula] = field(default_factory=list)
    macros: dict[str, str] = field(default_factory=dict)


def parse_arxiv_ref(text: str) -> str:
    """Normalize a bare ID or arXiv URL into a canonical arXiv ID.

    Accepts ``2403.12345``, ``2403.12345v2``, old-style ``hep-ph/9901001``,
    and arxiv.org / export.arxiv.org abs/pdf/e-print URLs.
    """
    ref = text.strip()
    if not ref:
        raise ArxivRefError("empty arXiv reference")
    match = re.match(
        r"^(?:https?://)?(?:export\.)?arxiv\.org/(?:abs|pdf|e-print|ps|format)/",
        ref,
        re.IGNORECASE,
    )
    if match:
        ref = ref[match.end():]
    ref = ref.strip().rstrip("/")
    new_style = re.fullmatch(r"(\d{4}\.\d{4,5})(v\d+)?", ref)
    old_style = re.fullmatch(
        r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}(v\d+)?", ref
    )
    if not (new_style or old_style):
        raise ArxivRefError(f"not a valid arXiv ID or URL: {text!r}")
    return ref


def strip_comments(tex: str) -> str:
    """Drop ``%`` comments while preserving line numbers.

    Newlines inside comments are kept so extraction line numbers stay
    truthful. ``\\%`` escapes are honored by counting the backslash run.
    """
    out: list[str] = []
    i = 0
    n = len(tex)
    while i < n:
        ch = tex[i]
        if ch == "%":
            backslashes = 0
            j = i - 1
            while j >= 0 and tex[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 1:  # escaped percent
                out.append(ch)
                i += 1
                continue
            while i < n and tex[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _read_group(tex: str, open_idx: int) -> str:
    """Read the balanced-brace group starting at ``tex[open_idx] == '{'``."""
    depth = 0
    i = open_idx
    n = len(tex)
    while i < n:
        ch = tex[i]
        if ch == "\\":
            i += 2  # skip the escaped character
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return tex[open_idx + 1 : i]
        i += 1
    raise ArxivSourceError("unbalanced braces in source")


def extract_macros(tex: str) -> dict[str, str]:
    """Collect preamble macro definitions in KaTeX ``macros`` format.

    Supports ``\\newcommand``, ``\\renewcommand``, ``\\def``, and
    ``\\DeclareMathOperator`` with balanced-brace bodies. Values keep
    ``#1``-style parameters so KaTeX expands them the same way TeX would.
    """
    macros: dict[str, str] = {}
    for match in _MACRO_DEF_RE.finditer(tex):
        if match.group(1):
            name = match.group(1)
        elif match.group(3):
            name = match.group(3)
        else:
            name = match.group(4)
        body_start = match.end() - 1  # position of the opening '{'
        if body_start >= len(tex) or tex[body_start] != "{":
            continue
        try:
            body = _read_group(tex, body_start)
        except ArxivSourceError:
            continue
        if name in macros or len(macros) >= MAX_MACRO_COUNT:
            continue
        if len(body) > MAX_MACRO_BODY_CHARS:
            continue
        if match.group(4):  # DeclareMathOperator → KaTeX operator wrapper
            body = f"\\operatorname{{{body}}}"
        macros[f"\\{name}"] = body.strip()
    return macros


def flatten_source(files: dict[str, str]) -> str:
    """Merge ``\\input``/``\\include`` chains into one comment-stripped text.

    The main file is the one declaring ``\\documentclass`` (largest wins on
    ties); fallback is the largest ``.tex`` file. Line numbers in extracted
    formulas refer to this flattened text.
    """
    main = None
    best_score = (-1, -1.0)
    for name, content in files.items():
        suffix = Path(name).suffix
        if suffix not in ("", ".tex", ".ltx"):
            continue
        has_class = "\\documentclass" in content
        score = (1 if has_class else 0, len(content))
        if score > best_score:
            best_score = score
            main = name
    if main is None:
        raise ArxivSourceError("archive contains no .tex source")

    merged: dict[str, str] = {}
    for name, content in files.items():
        merged[name] = strip_comments(content)

    seen: set[str] = set()

    def expand(name: str, depth: int = 0) -> str:
        if depth > 20 or name in seen:
            return ""
        seen.add(name)
        text = merged.get(name, "")
        out: list[str] = []
        last = 0
        for m in re.finditer(r"\\(?:input|include)\s*\{([^{}]+)\}", text):
            target = m.group(1).strip()
            candidates = [target, f"{target}.tex"]
            resolved = next((c for c in candidates if c in merged), None)
            if resolved is None:
                continue
            out.append(text[last : m.start()])
            out.append(f"\n{expand(resolved, depth + 1)}\n")
            last = m.end()
        out.append(text[last:])
        return "".join(out)

    return expand(main)


def _blank_verbatim(tex: str) -> str:
    """Replace verbatim-environment bodies with newlines (keeps line count)."""
    out = tex
    for env in _VERBATIM_ENVIRONMENTS:
        pattern = re.compile(
            rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}",
            re.DOTALL,
        )
        out = pattern.sub(lambda m: "\n" * m.group(0).count("\n"), out)
    return out


def _is_escaped(tex: str, idx: int) -> bool:
    """True when the character at ``idx`` follows an odd backslash run.

    An odd run means the character is escaped (``\\$``, or the second
    backslash of a ``\\\\[2pt]`` linebreak), so it cannot open math.
    """
    run = 0
    j = idx - 1
    while j >= 0 and tex[j] == "\\":
        run += 1
        j -= 1
    return run % 2 == 1


def extract_title(tex: str) -> str | None:
    match = _TITLE_RE.search(tex)
    if match is None:
        return None
    try:
        title = _read_group(tex, match.end() - 1)
    except ArxivSourceError:
        return None
    return re.sub(r"\s+", " ", title).strip() or None


def extract_formulas(tex: str) -> list[ExtractedFormula]:
    """Scan flattened, comment-stripped text for math fragments.

    Handles ``$...$``, ``$$...$$``, ``\\[..\\]``, ``\\(..\\)``, and the
    standard display environments. Labels are lifted out of the latex
    (KaTeX rejects ``\\label``) and reported as metadata.
    """
    tex = _blank_verbatim(tex)
    formulas: list[ExtractedFormula] = []
    section: str | None = None
    i = 0
    n = len(tex)
    last_math_end = 0

    def line_at(pos: int) -> int:
        return tex.count("\n", 0, pos) + 1

    def section_at(pos: int) -> str | None:
        best = None
        for m in _SECTION_RE.finditer(tex, 0, pos):
            best = m.group("title").strip()
        return best or section

    while i < n:
        ch = tex[i]

        if ch == "%":  # defensive: callers strip comments first
            while i < n and tex[i] != "\n":
                i += 1
            continue

        if ch == "\\":
            begin = _BEGIN_RE.match(tex, i)
            if begin is not None:
                env = begin.group(1)
                base = env.rstrip("*")
                end_marker = f"\\end{{{env}}}"
                end = tex.find(end_marker, begin.end())
                if base in _MATH_ENVIRONMENTS:
                    if end == -1:  # unclosed environment: skip the token
                        i = begin.end()
                        continue
                    body = tex[begin.end() : end]
                    _append_formula(
                        formulas, body, env, True, line_at(i),
                        section_at(i), tex, last_math_end, i,
                    )
                    last_math_end = end + len(end_marker)
                    i = last_math_end
                    continue
                if base in _VERBATIM_ENVIRONMENTS and end != -1:
                    i = end + len(end_marker)
                    continue
                i = begin.end()
                continue

            # \[ ... \]  and  \( ... \)  — not when part of \\[2pt]
            if tex.startswith("\\[", i) and not _is_escaped(tex, i):
                end = tex.find("\\]", i + 2)
                if end == -1:
                    i += 2
                    continue
                body = tex[i + 2 : end]
                _append_formula(
                    formulas, body, "display", True, line_at(i),
                    section_at(i), tex, last_math_end, i,
                )
                last_math_end = end + 2
                i = last_math_end
                continue
            if tex.startswith("\\(", i) and not _is_escaped(tex, i):
                end = tex.find("\\)", i + 2)
                if end == -1:
                    i += 2
                    continue
                body = tex[i + 2 : end]
                _append_formula(
                    formulas, body, "inline", False, line_at(i),
                    section_at(i), tex, last_math_end, i,
                )
                last_math_end = end + 2
                i = last_math_end
                continue
            i += 1
            continue

        if ch == "$":
            if _is_escaped(tex, i):
                i += 1
                continue
            if tex.startswith("$$", i):
                end = tex.find("$$", i + 2)
                if end == -1:
                    i += 2
                    continue
                body = tex[i + 2 : end]
                _append_formula(
                    formulas, body, "display", True, line_at(i),
                    section_at(i), tex, last_math_end, i,
                )
                last_math_end = end + 2
                i = last_math_end
                continue
            end = tex.find("$", i + 1)
            if end != -1 and not tex.startswith("$$", end):
                body = tex[i + 1 : end]
                _append_formula(
                    formulas, body, "inline", False, line_at(i),
                    section_at(i), tex, last_math_end, i,
                )
                last_math_end = end + 1
                i = last_math_end
                continue
            i += 1
            continue

        i += 1

    return formulas


def _append_formula(
    formulas: list[ExtractedFormula],
    body: str,
    env: str,
    display: bool,
    line: int,
    section: str | None,
    tex: str,
    last_math_end: int,
    start: int,
) -> None:
    latex = body.strip()
    if not latex or len(latex) > MAX_FORMULA_CHARS:
        return
    label = None
    label_match = _LABEL_RE.search(latex)
    if label_match is not None:
        label = label_match.group(1).strip() or None
        latex = _LABEL_RE.sub("", latex, count=1).strip()
    if not latex:
        return
    context = _context_snippet(tex, last_math_end, start)
    formulas.append(
        ExtractedFormula(
            index=len(formulas),
            latex=latex,
            env=env,
            display=display,
            line=line,
            section=section,
            label=label,
            context=context,
        )
    )


def _context_snippet(tex: str, last_math_end: int, start: int) -> str:
    window = tex[max(last_math_end, start - 600) : start]
    window = re.sub(r"\s+", " ", window).strip()
    return window[-CONTEXT_CHARS:]


def used_macros(latex: str, macros: dict[str, str]) -> dict[str, str]:
    """Return the transitive subset of macros a formula actually needs."""
    needed: dict[str, str] = {}
    queue = [latex]
    while queue:
        text = queue.pop()
        for name, body in macros.items():
            if name in needed or not re.search(
                re.escape(name) + r"(?![A-Za-z])", text
            ):
                continue
            needed[name] = body
            queue.append(body)
    return needed


def _safe_extract(data: bytes, dest: Path) -> None:
    """Unpack an arXiv e-print payload (tar or single-file gzip)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            members_all = tar.getmembers()
            if len(members_all) > MAX_ARCHIVE_MEMBERS:
                raise ArxivSourceError("archive has too many members")
            total = sum(m.size for m in members_all if m.isfile())
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ArxivSourceError("archive too large when unpacked")
            tar.extractall(path=dest, filter="data")
            return
    except tarfile.TarError:
        pass
    try:
        content = gzip.decompress(data)
    except OSError as exc:
        raise ArxivSourceError("payload is neither tar nor gzip") from exc
    (dest / "paper.tex").write_bytes(content)


def _read_source_files(directory: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        try:
            files[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return files


def load_cached(arxiv_id: str, cache_root: Path) -> ArxivPaper | None:
    """Rebuild a paper from a previous download without any network."""
    directory = cache_root / arxiv_id.replace("/", "_")
    meta_file = directory / "meta.json"
    if not meta_file.is_file():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        files = _read_source_files(directory)
        flattened = flatten_source(files)
    except (OSError, ValueError, ArxivSourceError):
        return None
    return _build_paper(meta.get("arxiv_id", arxiv_id), flattened, cached=True)


def _build_paper(arxiv_id: str, flattened: str, *, cached: bool) -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=extract_title(flattened),
        cached=cached,
        flattened=flattened,
        formulas=extract_formulas(flattened),
        macros=extract_macros(flattened),
    )


async def fetch_and_extract(
    arxiv_id: str,
    *,
    cache_root: Path,
    client: httpx.AsyncClient | None = None,
) -> ArxivPaper:
    """Fetch (or reuse) an arXiv source and extract its formulas.

    The download honors standard proxy environment variables through
    ``httpx`` trust_env, so no TeXada-specific proxy setting is needed.
    Network failures surface as ``ArxivSourceError`` for the API layer to
    map to 502; a PDF-only paper is a hard error, never an OCR fallback.
    """
    cached = load_cached(arxiv_id, cache_root)
    if cached is not None:
        return cached

    directory = cache_root / arxiv_id.replace("/", "_")
    directory.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30, read=120),
            headers={"User-Agent": "TeXada-arxiv-import/0.1"},
        )
    try:
        try:
            response = await client.get(f"{ARXIV_EPRINT_URL}{arxiv_id}")
        except httpx.HTTPError as exc:
            raise ArxivSourceError(f"could not reach arxiv.org: {exc}") from exc
        if response.status_code == 404:
            raise ArxivNotFoundError(f"arXiv has no paper {arxiv_id}")
        if response.status_code != 200:
            raise ArxivSourceError(
                f"arxiv.org returned HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type:
            raise ArxivNoSourceError(
                f"paper {arxiv_id} has no LaTeX source (PDF only)"
            )
        data = response.content
        if len(data) > MAX_SOURCE_BYTES:
            raise ArxivSourceError("source download exceeds size limit")
    finally:
        if own_client:
            await client.aclose()

    _safe_extract(data, directory)
    files = _read_source_files(directory)
    flattened = flatten_source(files)
    paper = _build_paper(arxiv_id, flattened, cached=False)
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "title": paper.title,
                "formula_count": len(paper.formulas),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return paper


def formula_by_index(paper: ArxivPaper, index: int) -> ExtractedFormula | None:
    if 0 <= index < len(paper.formulas):
        return paper.formulas[index]
    return None
