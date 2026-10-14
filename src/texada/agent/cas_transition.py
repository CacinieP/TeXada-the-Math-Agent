"""Shadow algebra evidence for explicitly preserving formula transitions."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from texada.cas import AlgebraChecker, CASResult
from texada.runtime import FormulaState
from texada.semantic import SemanticParser
from texada.semantic.structure import UnsupportedStructure, canonical_structure

TRANSITION_POLICY = "cas-transition-shadow-v1"


class TransitionApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"


class TransitionVerdict(StrEnum):
    NOT_CHECKED = "not_checked"
    EQUIVALENT = "equivalent"
    DIFFERENT = "different"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass
class TransitionEvidence:
    parent_revision: int | None
    child_revision: int
    parent_latex_sha256: str | None
    child_latex_sha256: str
    semantics_preserving_declared: bool
    scope_verdict: str
    applicability: TransitionApplicability = TransitionApplicability.NOT_APPLICABLE
    verdict: TransitionVerdict = TransitionVerdict.NOT_CHECKED
    basis: str = "no_comparison"
    witness: dict[str, Any] | None = None
    cas_result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    policy_version: str = TRANSITION_POLICY
    mode: str = "shadow"
    blocks_commit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash(latex: str) -> str:
    return hashlib.sha256(latex.encode("utf-8")).hexdigest()


def _digit(node: dict[str, Any]) -> str | None:
    value = node.get("value")
    if node.get("kind") == "symbol" and isinstance(value, str) and re.fullmatch("[0-9]", value):
        return value
    return None


def _integer_argument(role: dict[str, Any], *, positive: bool) -> bool:
    children = role.get("children", [])
    # The existing SemanticUnit mapper does not coalesce adjacent digit nodes.
    # Keep this shadow subset to single-digit exact constants, rather than
    # comparing an incorrect translation of e.g. 12 as 1*2.
    if len(children) == 1:
        value = _digit(children[0])
        return value is not None and (not positive or value != "0")
    return (
        not positive
        and len(children) == 2
        and children[0].get("value") == "-"
        and _digit(children[1]) not in {None, "0"}
    )


def _reliable_scalar_subset(nodes: list[dict[str, Any]]) -> None:
    """Prevent known lossy presentation/domain cases from reaching the CAS."""
    for index, node in enumerate(nodes):
        if index and _digit(node) is not None and _digit(nodes[index - 1]) is not None:
            raise UnsupportedStructure("adjacent_digit_translation_not_validated")
        kind = node.get("kind")
        if kind == "symbol":
            value = node.get("value", "")
            if value in {"e", "i"} or not re.fullmatch(r"[A-Za-z0-9+*=\-]", value):
                raise UnsupportedStructure("scalar_symbol_not_validated")
        elif kind == "fraction":
            if not node.get("has_bar_line") or node.get("left") or node.get("right"):
                raise UnsupportedStructure("binomial_or_fraction_delimiters_not_translatable")
            roles = {item["role"]: item for item in node["children"]}
            if not _integer_argument(roles["denominator"], positive=True):
                raise UnsupportedStructure("variable_or_zero_denominator_domain_not_validated")
            _reliable_scalar_subset(roles["numerator"]["children"])
        elif kind == "script":
            roles = {item["role"]: item for item in node["children"]}
            if set(roles) != {"base", "superscript"} or not _integer_argument(
                roles["superscript"],
                positive=True,
            ):
                raise UnsupportedStructure("subscript_or_nonpositive_power_not_validated")
            _reliable_scalar_subset(roles["base"]["children"])
        elif kind == "delimited":
            if (node["left"], node["right"]) != ("(", ")"):
                raise UnsupportedStructure("non_parenthesis_delimiters_not_translatable")
            _reliable_scalar_subset(node["children"])
        else:
            raise UnsupportedStructure(f"scalar_kind_not_validated:{kind}")


class CASTransitionChecker:
    """Use the existing bounded AlgebraChecker after a stronger raw AST check.

    This version compares only rational-coefficient polynomials and polynomial
    equations. It makes no claim about domain-sensitive rational cancellation,
    integrals, roots, matrices, OCR correction, or NL translation fidelity.
    """

    def __init__(
        self,
        *,
        checker: AlgebraChecker | None = None,
        deadline_monotonic: float | None = None,
    ):
        self.checker = checker or AlgebraChecker(timeout_ms=1000)
        self.deadline_monotonic = deadline_monotonic
        self.parser = SemanticParser()

    def check(
        self,
        before: str | None,
        after: str,
        *,
        parent_revision: int | None,
        child_revision: int,
        semantics_preserving_declared: bool,
        scope_verdict: str = "not_checked",
    ) -> TransitionEvidence:
        evidence = TransitionEvidence(
            parent_revision,
            child_revision,
            _hash(before) if before else None,
            _hash(after),
            semantics_preserving_declared,
            scope_verdict,
        )
        if parent_revision is None or not before:
            evidence.basis = "no_parent_revision"
            return evidence
        if not semantics_preserving_declared:
            evidence.basis = "transition_not_declared_preserving"
            return evidence
        if self.deadline_monotonic is not None and self.deadline_monotonic <= time.monotonic():
            return self.timed_out(evidence)
        try:
            for latex in (before, after):
                if len(latex) > 2048:
                    raise UnsupportedStructure("shadow_expression_size_limit")
                tree, _ = canonical_structure(latex)
                if not tree:
                    raise UnsupportedStructure("empty_expression")
                _reliable_scalar_subset(tree)
        except UnsupportedStructure as exc:
            evidence.applicability = TransitionApplicability.UNSUPPORTED
            evidence.verdict = TransitionVerdict.UNSUPPORTED
            evidence.basis = "raw_ast_translation_boundary"
            evidence.reason = str(exc)
            return evidence
        except Exception:
            evidence.applicability = TransitionApplicability.UNSUPPORTED
            evidence.verdict = TransitionVerdict.UNSUPPORTED
            evidence.basis = "raw_ast_parser_unavailable"
            return evidence
        evidence.applicability = TransitionApplicability.APPLICABLE
        if self.deadline_monotonic is not None:
            # Leave two seconds for parent translation, process cleanup and
            # scheduling. Startup and comparison split the remaining budget.
            remaining = self.deadline_monotonic - time.monotonic() - 2.0
            if remaining <= 0:
                return self.timed_out(evidence)
            timeout_ms = max(1, min(1000, int(remaining * 500)))
            self.checker.timeout_ms = timeout_ms
            self.checker.worker.startup_timeout_ms = max(1, int(remaining * 1000) - timeout_ms)
        try:
            result: CASResult = self.checker.check(
                self.parser.parse(before), self.parser.parse(after)
            )
        except Exception:
            evidence.verdict = TransitionVerdict.UNKNOWN
            evidence.basis = "comparison_failed"
            evidence.reason = "CAS comparison could not complete"
            return evidence
        evidence.verdict = TransitionVerdict(result.status.value)
        evidence.basis = result.basis.value
        evidence.witness = result.witness
        evidence.cas_result = result.to_dict()
        evidence.reason = result.reason
        if evidence.verdict == TransitionVerdict.UNSUPPORTED:
            evidence.applicability = TransitionApplicability.UNSUPPORTED
        return evidence

    def record(self, state: FormulaState) -> None:
        """Attach each new parent/child verdict to the exact child revision."""
        for result in self.evaluate(state):
            self.attach(state, result)

    def evaluate(self, state: FormulaState) -> list[TransitionEvidence]:
        """Return evidence without changing state; safe for a bounded worker thread."""
        recorded = {
            item.revision for item in state.ledger.evidence if item.kind == "cas_transition"
        }
        scopes = {
            item.revision: item.output
            for item in state.ledger.evidence
            if item.kind == "mutation_scope"
        }
        results = []
        for child in state.ledger.revisions:
            if child.number in recorded:
                continue
            scope = scopes.get(child.number, {})
            result = self.check(
                state.latex_at(child.parent) if child.parent is not None else None,
                child.latex,
                parent_revision=child.parent,
                child_revision=child.number,
                semantics_preserving_declared=scope.get("semantics_preserving_declared") is True,
                scope_verdict=str(scope.get("verdict", "not_checked")),
            )
            results.append(result)
        return results

    @staticmethod
    def attach(state: FormulaState, result: TransitionEvidence) -> None:
        state.add_evidence(
            revision=result.child_revision,
            kind="cas_transition",
            ok=result.verdict == TransitionVerdict.EQUIVALENT,
            output=result.to_dict(),
        )

    @staticmethod
    def timed_out(evidence: TransitionEvidence) -> TransitionEvidence:
        evidence.applicability = TransitionApplicability.APPLICABLE
        evidence.verdict = TransitionVerdict.TIMEOUT
        evidence.basis = "request_or_tool_budget_exhausted"
        evidence.reason = "shadow CAS did not finish within the request and tool budget"
        return evidence

    @staticmethod
    def pending(state: FormulaState, *, timed_out: bool = True) -> list[TransitionEvidence]:
        """Generate bounded, typed timeout evidence without running algebra."""
        recorded = {
            item.revision for item in state.ledger.evidence if item.kind == "cas_transition"
        }
        scopes = {
            item.revision: item.output
            for item in state.ledger.evidence
            if item.kind == "mutation_scope"
        }
        results = []
        for child in state.ledger.revisions:
            if child.number in recorded:
                continue
            scope = scopes.get(child.number, {})
            result = TransitionEvidence(
                child.parent,
                child.number,
                _hash(state.latex_at(child.parent)) if child.parent is not None else None,
                _hash(child.latex),
                scope.get("semantics_preserving_declared") is True,
                str(scope.get("verdict", "not_checked")),
            )
            if child.parent is None:
                result.basis = "no_parent_revision"
            elif not result.semantics_preserving_declared:
                result.basis = "transition_not_declared_preserving"
            elif timed_out:
                CASTransitionChecker.timed_out(result)
            else:
                result.basis = "run_stopped_before_shadow"
                result.reason = "run stopped before shadow comparison"
            results.append(result)
        return results

    @staticmethod
    def failed(state: FormulaState) -> list[TransitionEvidence]:
        results = CASTransitionChecker.pending(state, timed_out=False)
        for result in results:
            if result.parent_revision is not None and result.semantics_preserving_declared:
                result.verdict = TransitionVerdict.UNKNOWN
                result.applicability = TransitionApplicability.APPLICABLE
                result.basis = "shadow_comparison_failed"
                result.reason = "shadow comparison could not complete"
        return results

    def close(self) -> None:
        self.checker.close()
