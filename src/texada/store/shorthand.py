"""Shorthand Store — zero-model lookup table."""
from __future__ import annotations

import json
import os

from texada.config import TeXadaConfig
from texada.core.validator import LaTeXValidator

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
        self.validator = LaTeXValidator()
        self._shorthands: dict[str, str] = {}
        self._file = config.data_dir / "shorthands.json"
        self._load()

    def _load(self) -> None:
        # Start with defaults
        self._shorthands = dict(DEFAULT_SHORTHANDS)
        # Overlay user-defined
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            for key, value in data.get("shorthands", {}).items():
                if key not in DEFAULT_SHORTHANDS and isinstance(value, str):
                    self._shorthands[key] = value

    def _save(self) -> None:
        user_only = {
            k: v for k, v in self._shorthands.items()
            if k not in DEFAULT_SHORTHANDS or DEFAULT_SHORTHANDS[k] != v
        }
        data = {"_meta": {"version": 1}, "shorthands": user_only}
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._file.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self._file)

    def has(self, key: str) -> bool:
        return key.strip() in self._shorthands

    def lookup(self, key: str) -> str | None:
        return self._shorthands.get(key.strip())

    def list_all(self, query: str = "") -> list[tuple[str, str]]:
        items = list(self._shorthands.items())
        if query:
            items = [(k, v) for k, v in items if query in k or query in v]
        return sorted(items)

    def list_user_defined(self) -> dict[str, str]:
        """Return only user-owned shorthands for backup/export."""
        return {
            k: v for k, v in self._shorthands.items()
            if k not in DEFAULT_SHORTHANDS or DEFAULT_SHORTHANDS[k] != v
        }

    def can_delete(self, key: str) -> bool:
        return key in self._shorthands and key not in DEFAULT_SHORTHANDS

    def add(self, key: str, value: str) -> None:
        normalized_key, normalized_value = self._validate_pair(key, value)
        self._shorthands[normalized_key] = normalized_value
        self._save()

    def import_many(
        self,
        items: dict[str, str],
        *,
        mode: str = "merge",
    ) -> dict[str, int]:
        """Import user shorthands while always preserving built-in presets."""
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"merge", "replace"}:
            raise ValueError("mode must be 'merge' or 'replace'")

        imported = 0
        skipped = 0
        cleared = 0
        if normalized_mode == "replace":
            existing_user_keys = list(self.list_user_defined())
            for key in existing_user_keys:
                if key in DEFAULT_SHORTHANDS:
                    self._shorthands[key] = DEFAULT_SHORTHANDS[key]
                else:
                    self._shorthands.pop(key, None)
            cleared = len(existing_user_keys)

        for key, value in items.items():
            try:
                normalized_key, normalized_value = self._validate_pair(key, value)
            except (TypeError, ValueError):
                skipped += 1
                continue
            self._shorthands[normalized_key] = normalized_value
            imported += 1
        if imported or cleared:
            self._save()
        return {"imported": imported, "skipped": skipped, "cleared": cleared}

    def delete(self, key: str) -> bool:
        if self.can_delete(key):
            del self._shorthands[key]
            self._save()
            return True
        return False

    def _validate_pair(self, key: object, value: object) -> tuple[str, str]:
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("preset key and value must be strings")
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            raise ValueError("preset key and value must not be empty")
        if len(normalized_key) > 100 or len(normalized_value) > 4000:
            raise ValueError("preset exceeds the supported size")
        if normalized_key in DEFAULT_SHORTHANDS:
            raise ValueError(f"built-in preset '{normalized_key}' cannot be replaced")
        validation = self.validator.validate(normalized_value)
        if not validation.valid:
            detail = validation.errors[0].detail or validation.errors[0].error
            raise ValueError(detail or "preset value is not valid LaTeX")
        return normalized_key, normalized_value
