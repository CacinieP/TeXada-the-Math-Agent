"""Data model for TeXada semantic math units."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SemanticUnit:
    """A mathematical unit whose identity is structural, not character based."""

    kind: str
    value: str = ""
    role: str = ""
    children: list[SemanticUnit] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def to_dict(self, *, include_source: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "value": self.value,
            "role": self.role,
            "attributes": self.attributes,
            "children": [child.to_dict(include_source=include_source) for child in self.children],
        }
        if include_source:
            data["source"] = self.source
        return data

    @property
    def label(self) -> str:
        if self.value:
            return f"{self.kind}:{self.value}"
        return self.kind

    def fingerprint(self) -> str:
        """Return a stable hash of semantic content, excluding source spelling."""
        payload = {
            "kind": self.kind,
            "value": self.value,
            "role": self.role,
            "attributes": self.attributes,
            "children": [child.fingerprint() for child in self.children],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class SemanticDocument:
    """Parsed LaTeX plus its semantic tree and non-fatal parse diagnostics."""

    latex: str
    root: SemanticUnit
    diagnostics: list[str] = field(default_factory=list)
    parser_backend: str = "fallback"
    schema_version: int = 1

    def to_dict(self, *, include_source: bool = True) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "latex": self.latex,
            "parser_backend": self.parser_backend,
            "root": self.root.to_dict(include_source=include_source),
            "diagnostics": self.diagnostics,
        }


@dataclass
class SemanticChange:
    """One structural edit between two semantic documents."""

    operation: str
    path: str
    unit_kind: str
    before: str | None = None
    after: str | None = None
    role: str = ""
    cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "path": self.path,
            "unit_kind": self.unit_kind,
            "role": self.role,
            "before": self.before,
            "after": self.after,
            "cost": round(self.cost, 4),
        }


@dataclass
class SemanticDiff:
    """Structural comparison result for two LaTeX expressions."""

    equivalent: bool
    changes: list[SemanticChange] = field(default_factory=list)
    before: SemanticDocument | None = None
    after: SemanticDocument | None = None
    weighted_cost: float = 0.0
    normalization_weight: float = 1.0
    normalized_distance: float = 0.0
    semantic_similarity: float = 1.0

    def to_dict(self, *, include_documents: bool = False) -> dict[str, Any]:
        structure_kinds = {
            "fraction",
            "root",
            "integral",
            "summation",
            "product",
            "limit",
            "script",
            "environment",
        }
        structural = sum(change.unit_kind in structure_kinds for change in self.changes)
        data: dict[str, Any] = {
            "algorithm": "role-aware-weighted-ordered-tree-edit",
            "equivalent": self.equivalent,
            "change_count": len(self.changes),
            "structural_change_count": structural,
            "weighted_cost": round(self.weighted_cost, 4),
            "normalization_weight": round(self.normalization_weight, 4),
            "normalized_distance": round(self.normalized_distance, 6),
            "semantic_similarity": round(self.semantic_similarity, 6),
            "reward": round(self.semantic_similarity, 6),
            "changes": [change.to_dict() for change in self.changes],
        }
        if include_documents:
            data["before"] = self.before.to_dict() if self.before else None
            data["after"] = self.after.to_dict() if self.after else None
        return data
