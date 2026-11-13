"""Helpers for the real-world NL → LaTeX corpus (``eval/real_world_set.yaml``)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from anchor_match import anchor_present
from golden_lib import anchor_variants

from texada.semantic.parser import SemanticParser

REPO = Path(__file__).resolve().parents[1]
REAL_WORLD_SET = REPO / "eval" / "real_world_set.yaml"

CATEGORIES = (
    "named-formula",
    "lecture-sentence",
    "common-mistake",
    "no-solving",
    "completion",
)

_PARSER = SemanticParser()
_CJK = re.compile(r"[\u4e00-\u9fff]")
# Label groups are part of the formula (``\text{ 偶 }``); only text *outside*
# them counts as prose leakage.
_TEXT_GROUP = re.compile(
    r"\\(?:text|mathrm|mathbf|mathsf|mathtt|operatorname|textbf|textit|textrm)"
    r"\s*\{[^{}]*\}"
)
_TEXT_ONLY = re.compile(r"^\s*\\text\{[^{}]*\}\s*$")
_DELIMITERS = (
    (r"^\$\$", r"\$\$$"),
    (r"^\\\[", r"\\\]$"),
    (r"^\$", r"\$$"),
)


def load_real_world_set(path: Path = REAL_WORLD_SET) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["entries"]


def strip_delimiters(latex: str) -> str:
    """Drop one layer of ``$$``/``$``/``\\[ \\]`` wrapping the model may add."""
    text = (latex or "").strip()
    for opening, closing in _DELIMITERS:
        if re.search(opening, text) and re.search(closing, text):
            text = re.sub(opening, "", text, count=1)
            text = re.sub(closing, "", text, count=1)
            break
    return text.strip()


def parse_ok(latex: str) -> tuple[bool, str]:
    """Whether KaTeX accepts the string (the product's only syntax authority)."""
    if not latex.strip():
        return False, "empty"
    doc = _PARSER.parse(latex)
    if doc.parser_backend.startswith("katex"):
        return True, ""
    detail = "; ".join(doc.diagnostics[:2]) or "tolerant fallback used"
    return False, detail


def text_only(latex: str) -> bool:
    """True when the output is prose/one ``\\text{}`` label instead of a formula."""
    text = strip_delimiters(latex)
    if _TEXT_ONLY.match(text):
        return True
    return "\\" not in text and not re.search(r"[=^_<>+\-*/]", text)


def prose_leak(latex: str) -> bool:
    """True when CJK appears outside ``\\text{}`` groups (i.e. it explained instead)."""
    body = _TEXT_GROUP.sub("", strip_delimiters(latex))
    return bool(_CJK.search(body))


def forbidden_hits(latex: str, forbids: list[str] | None) -> list[str]:
    text = strip_delimiters(latex)
    return [f for f in (forbids or []) if f and f in text]


def anchor_hit(latex: str, anchor: str) -> bool:
    variants = anchor_variants(anchor)
    if not variants:
        return True  # purely descriptive anchor: no machine-checkable layer
    return any(anchor_present(strip_delimiters(latex), v) for v in variants)


def judge(entry: dict, latex: str) -> tuple[bool, list[str]]:
    """Apply the corpus rules to one model output. Returns (ok, reasons)."""
    reasons: list[str] = []
    text = strip_delimiters(latex)
    if not text:
        return False, ["empty output"]
    if text_only(text):
        reasons.append("text-only output (no formula)")
    else:
        ok, detail = parse_ok(text)
        if not ok:
            reasons.append(f"KaTeX parse failed: {detail}")
    if prose_leak(text):
        reasons.append("CJK prose outside \\text{} (explained instead of transcribing)")
    hits = forbidden_hits(text, entry.get("forbid"))
    if hits:
        reasons.append(f"forbidden fragment(s): {hits}")
    if not anchor_hit(text, entry.get("anchor", "")):
        reasons.append(f"anchor missing: {entry.get('anchor')!r}")
    return not reasons, reasons
