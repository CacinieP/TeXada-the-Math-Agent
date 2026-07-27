"""Deterministic LaTeX repair used by the ``repair_tex`` tool.

This module is deliberately not a model adapter. TeXada has exactly two model
roles: MiniCPM5-1B for planning/text generation and MiniCPM-V 4.6 for vision
OCR. Syntax repair remains a small, local, deterministic tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from texada.core.fixer import LaTeXFixer
from texada.core.validator import LaTeXValidator
from texada.semantic import SemanticDiffer
from texada.types import CheckResult


@dataclass
class DeterministicRepairResult:
    """Validated result returned by the deterministic repair service."""

    original: str
    latex: str
    changed: bool
    valid: bool
    repair_method: str = "deterministic-rules"
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    semantic_diff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "latex": self.latex,
            "changed": self.changed,
            "valid": self.valid,
            "repair_method": self.repair_method,
            "diagnostics": self.diagnostics,
            "log": self.log,
            "semantic_diff": self.semantic_diff,
        }


class DeterministicRepairService:
    """Apply the existing fixer, revalidate, and report the structural change."""

    def __init__(
        self,
        *,
        fixer: LaTeXFixer | None = None,
        validator: LaTeXValidator | None = None,
        differ: SemanticDiffer | None = None,
    ):
        self.fixer = fixer or LaTeXFixer()
        self.validator = validator or LaTeXValidator()
        self.differ = differ or SemanticDiffer()

    def repair(
        self,
        latex: str,
        diagnostics: list[CheckResult] | None = None,
    ) -> DeterministicRepairResult:
        validation = self.validator.validate(latex)
        errors = diagnostics if diagnostics is not None else validation.errors
        fixed = self.fixer.fix(latex, errors)
        candidate = fixed.latex.strip() or latex
        candidate_validation = self.validator.validate(candidate)

        return DeterministicRepairResult(
            original=latex,
            latex=candidate,
            changed=candidate != latex,
            valid=candidate_validation.valid,
            diagnostics=[
                {
                    "type": item.type,
                    "detail": item.detail,
                    "error": item.error,
                }
                for item in candidate_validation.errors
            ],
            log=fixed.log,
            semantic_diff=self.differ.diff(latex, candidate).to_dict(),
        )
