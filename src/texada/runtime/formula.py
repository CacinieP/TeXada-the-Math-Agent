"""Revision-bound formula state, evidence, and commit barrier.

The Formula Runtime is deliberately independent from the planner and tool wire
protocols. It owns the authoritative LaTeX value for one Agent run and records
every accepted mutation as an append-only revision.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class StaleRevisionError(RuntimeError):
    """Raised when a mutation or commit targets an obsolete revision."""


class CommitBarrierError(RuntimeError):
    """Raised when the current revision lacks commit-grade evidence."""


@dataclass(frozen=True)
class FormulaRevision:
    """One immutable formula value in the append-only revision chain."""

    number: int
    latex: str
    parent: int | None
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "latex": self.latex,
            "parent": self.parent,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class FormulaEvidence:
    """A tool observation explicitly bound to the revision it inspected."""

    sequence: int
    revision: int
    kind: str
    ok: bool
    output: dict[str, Any]
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "revision": self.revision,
            "kind": self.kind,
            "ok": self.ok,
            "output": deepcopy(self.output),
            "error": self.error,
        }


@dataclass(frozen=True)
class FormulaCommit:
    """A successful commit of one exact revision and its proof evidence."""

    sequence: int
    revision: int
    evidence: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "revision": self.revision,
            "evidence": list(self.evidence),
        }


class FormulaLedger:
    """Append-only in-memory ledger for a single formula run."""

    def __init__(self) -> None:
        self._revisions: list[FormulaRevision] = []
        self._evidence: list[FormulaEvidence] = []
        self._commits: list[FormulaCommit] = []

    @property
    def revisions(self) -> tuple[FormulaRevision, ...]:
        return tuple(self._revisions)

    @property
    def evidence(self) -> tuple[FormulaEvidence, ...]:
        return tuple(
            FormulaEvidence(
                sequence=item.sequence,
                revision=item.revision,
                kind=item.kind,
                ok=item.ok,
                output=deepcopy(item.output),
                error=item.error,
            )
            for item in self._evidence
        )

    @property
    def commits(self) -> tuple[FormulaCommit, ...]:
        return tuple(self._commits)

    @property
    def current(self) -> FormulaRevision | None:
        return self._revisions[-1] if self._revisions else None

    def get_revision(self, number: int) -> FormulaRevision:
        return self._require_revision(number)

    def append_revision(
        self,
        latex: str,
        *,
        expected_revision: int | None,
        origin: str,
    ) -> FormulaRevision:
        normalized = latex.strip()
        if not normalized:
            raise ValueError("formula revision must contain non-empty LaTeX")

        current = self.current
        current_number = current.number if current else None
        if expected_revision != current_number:
            raise StaleRevisionError(
                "formula mutation expected revision "
                f"{expected_revision}, current revision is {current_number}"
            )
        if current and current.latex == normalized:
            return current

        revision = FormulaRevision(
            number=len(self._revisions) + 1,
            latex=normalized,
            parent=current_number,
            origin=origin.strip() or "unspecified",
        )
        self._revisions.append(revision)
        return revision

    def add_evidence(
        self,
        *,
        revision: int,
        kind: str,
        ok: bool,
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> FormulaEvidence:
        self._require_revision(revision)
        normalized_kind = kind.strip()
        if not normalized_kind:
            raise ValueError("formula evidence kind must be non-empty")
        item = FormulaEvidence(
            sequence=len(self._evidence) + 1,
            revision=revision,
            kind=normalized_kind,
            ok=bool(ok),
            output=deepcopy(output or {}),
            error=error,
        )
        self._evidence.append(item)
        return item

    def commit(self, *, expected_revision: int) -> FormulaCommit:
        current = self.current
        current_number = current.number if current else None
        if expected_revision != current_number:
            raise StaleRevisionError(
                "formula commit expected revision "
                f"{expected_revision}, current revision is {current_number}"
            )

        prior = next(
            (item for item in reversed(self._commits) if item.revision == expected_revision),
            None,
        )
        if prior is not None:
            return prior

        compile_evidence = self._latest_evidence(expected_revision, "compile_tex")
        render_evidence = self._latest_evidence(expected_revision, "render_math")
        if not (
            compile_evidence
            and compile_evidence.ok
            and compile_evidence.output.get("valid") is True
        ):
            raise CommitBarrierError(
                f"revision {expected_revision} lacks successful compile evidence"
            )
        if not (render_evidence and render_evidence.ok):
            raise CommitBarrierError(
                f"revision {expected_revision} lacks successful render evidence"
            )

        commit = FormulaCommit(
            sequence=len(self._commits) + 1,
            revision=expected_revision,
            evidence=(compile_evidence.sequence, render_evidence.sequence),
        )
        self._commits.append(commit)
        return commit

    def projection(self) -> dict[str, Any]:
        """Return the compact planner-facing view of the current state."""
        current = self.current
        if current is None:
            return {
                "revision": None,
                "latex": "",
                "committed": False,
                "evidence": [],
            }

        latest_by_kind: dict[str, FormulaEvidence] = {}
        for item in self._evidence:
            if item.revision == current.number:
                latest_by_kind[item.kind] = item
        return {
            "revision": current.number,
            "latex": current.latex,
            "committed": any(
                item.revision == current.number for item in self._commits
            ),
            "evidence": [
                {
                    "kind": item.kind,
                    "ok": item.ok,
                    "sequence": item.sequence,
                }
                for item in latest_by_kind.values()
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        current = self.current
        return {
            "current_revision": current.number if current else None,
            "revisions": [item.to_dict() for item in self._revisions],
            "evidence": [item.to_dict() for item in self._evidence],
            "commits": [item.to_dict() for item in self._commits],
        }

    def _require_revision(self, revision: int) -> FormulaRevision:
        if revision < 1 or revision > len(self._revisions):
            raise ValueError(f"unknown formula revision: {revision}")
        return self._revisions[revision - 1]

    def _latest_evidence(
        self,
        revision: int,
        kind: str,
    ) -> FormulaEvidence | None:
        return next(
            (
                item
                for item in reversed(self._evidence)
                if item.revision == revision and item.kind == kind
            ),
            None,
        )


class FormulaState:
    """The sole mutable authority for the formula inside one Agent run."""

    def __init__(self, latex: str = "", *, origin: str = "input") -> None:
        self.ledger = FormulaLedger()
        if latex.strip():
            self.ledger.append_revision(
                latex,
                expected_revision=None,
                origin=origin,
            )

    @property
    def revision(self) -> int | None:
        current = self.ledger.current
        return current.number if current else None

    @property
    def latex(self) -> str:
        current = self.ledger.current
        return current.latex if current else ""

    def latex_at(self, revision: int) -> str:
        """Return one immutable historical value without changing current state."""
        return self.ledger.get_revision(revision).latex

    @property
    def committed(self) -> bool:
        revision = self.revision
        return bool(
            revision is not None
            and any(item.revision == revision for item in self.ledger.commits)
        )

    def revise(
        self,
        latex: str,
        *,
        expected_revision: int | None,
        origin: str,
    ) -> FormulaRevision:
        return self.ledger.append_revision(
            latex,
            expected_revision=expected_revision,
            origin=origin,
        )

    def add_evidence(
        self,
        *,
        revision: int,
        kind: str,
        ok: bool,
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> FormulaEvidence:
        return self.ledger.add_evidence(
            revision=revision,
            kind=kind,
            ok=ok,
            output=output,
            error=error,
        )

    def commit(self, *, expected_revision: int) -> FormulaCommit:
        return self.ledger.commit(expected_revision=expected_revision)

    def planner_projection(self) -> dict[str, Any]:
        return self.ledger.projection()

    def to_dict(self) -> dict[str, Any]:
        return self.ledger.to_dict()
