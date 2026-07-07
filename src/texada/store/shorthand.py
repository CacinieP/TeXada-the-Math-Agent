"""Shorthand Store — zero-model lookup table."""
from __future__ import annotations

import json

from texada.config import TeXadaConfig

# Default shorthands shipped with TeXada
DEFAULT_SHORTHANDS: dict[str, str] = {
    "euler":   "e^{i\\pi}+1=0",
    "euler-g": "e^{i\\theta}=\\cos\\theta+i\\sin\\theta",
    "pyth":    "a^2+b^2=c^2",
    "quad":    "x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}",
    "binom":   "\\binom{n}{k}=\\frac{n!}{k!(n-k)!}",
    "taylor":  "f(x)=\\sum_{n=0}^{\\infty}\\frac{f^{(n)}(a)}{n!}(x-a)^n",
    "gauss":   "\\int_{-\\infty}^{\\infty}e^{-x^2}dx=\\sqrt{\\pi}",
    "fourier": "\\hat{f}(\\xi)=\\int_{-\\infty}^{\\infty}f(x)e^{-2\\pi ix\\xi}dx",
    "normal":  "f(x)=\\frac{1}{\\sigma\\sqrt{2\\pi}}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}",
    "bayes":   "P(A|B)=\\frac{P(B|A)P(A)}{P(B)}",
    "stokes": (
        "\\oint_C \\mathbf{F}\\cdot d\\mathbf{r}"
        "=\\iint_S(\\nabla\\times\\mathbf{F})\\cdot d\\mathbf{S}"
    ),
    "green": (
        "\\oint_C(Pdx+Qdy)"
        "=\\iint_D\\left(\\frac{\\partial Q}{\\partial x}"
        "-\\frac{\\partial P}{\\partial y}\\right)dA"
    ),
}


class ShorthandStore:
    """Built-in + user-defined shorthand lookup."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._shorthands: dict[str, str] = {}
        self._file = config.data_dir / "shorthands.json"
        self._load()

    def _load(self) -> None:
        # Start with defaults
        self._shorthands = dict(DEFAULT_SHORTHANDS)
        # Overlay user-defined
        if self._file.exists():
            with open(self._file) as f:
                data = json.load(f)
                if "shorthands" in data:
                    self._shorthands.update(data["shorthands"])

    def _save(self) -> None:
        user_only = {
            k: v for k, v in self._shorthands.items()
            if k not in DEFAULT_SHORTHANDS or DEFAULT_SHORTHANDS[k] != v
        }
        data = {"_meta": {"version": 1}, "shorthands": user_only}
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def has(self, key: str) -> bool:
        return key.strip() in self._shorthands

    def lookup(self, key: str) -> str | None:
        return self._shorthands.get(key.strip())

    def list_all(self, query: str = "") -> list[tuple[str, str]]:
        items = list(self._shorthands.items())
        if query:
            items = [(k, v) for k, v in items if query in k or query in v]
        return sorted(items)

    def add(self, key: str, value: str) -> None:
        self._shorthands[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        if key in self._shorthands and key not in DEFAULT_SHORTHANDS:
            del self._shorthands[key]
            self._save()
            return True
        return False
