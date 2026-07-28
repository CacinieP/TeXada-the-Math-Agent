"""Auditable result types for TeXada's optional CAS capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CASStatus(StrEnum):
    """Product-facing conclusion, kept separate from supporting evidence."""

    EQUIVALENT = "equivalent"
    DIFFERENT = "different"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class CASBasis(StrEnum):
    """Evidence used to justify a CAS conclusion."""

    EXACT_NORMALIZATION = "exact_normalization"
    EXACT_COUNTEREXAMPLE = "exact_counterexample"
    EQUATION_CONSTANT_FACTOR = "equation_constant_factor"
    SYMPY_EQUALS_TRUE = "sympy_equals_true"
    SYMPY_EQUALS_FALSE_OBSERVATION = "sympy_equals_false_observation"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED_SEMANTIC_UNIT = "unsupported_semantic_unit"
    UNSAFE_EVALUATION_RESULT = "unsafe_evaluation_result"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    WORKER_TIMEOUT = "worker_timeout"
    WORKER_MEMORY_LIMIT = "worker_memory_limit"
    WORKER_ERROR = "worker_error"


class CASEvidenceGrade(StrEnum):
    """Strength of the evidence, independent of the product-facing status."""

    EXACT = "exact"
    SYMBOLIC_HEURISTIC = "symbolic_heuristic"
    OBSERVATION = "observation"
    NONE = "none"


@dataclass
class CASResult:
    """A conclusion plus enough evidence to audit how it was reached."""

    status: CASStatus
    basis: CASBasis
    evidence_grade: CASEvidenceGrade = CASEvidenceGrade.NONE
    assumptions: list[str] = field(default_factory=list)
    witness: dict[str, Any] | None = None
    lhs_value: Any | None = None
    rhs_value: Any | None = None
    observation: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    reason_code: str = ""
    seed: int | None = None
    sympy_version: str = ""
    policy_version: str = ""
    cache_key: str = ""
    duration_ms: float = 0.0

    @property
    def verified(self) -> bool:
        """Only positive equivalence evidence qualifies as verified."""
        return self.status is CASStatus.EQUIVALENT

    @property
    def verified_exact(self) -> bool:
        return self.verified and self.evidence_grade is CASEvidenceGrade.EXACT

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "basis": self.basis.value,
            "verified": self.verified,
            "verified_exact": self.verified_exact,
            "evidence_grade": self.evidence_grade.value,
            "assumptions": self.assumptions,
            "witness": self.witness,
            "lhs_value": self.lhs_value,
            "rhs_value": self.rhs_value,
            "observation": self.observation,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "seed": self.seed,
            "sympy_version": self.sympy_version,
            "policy_version": self.policy_version,
            "cache_key": self.cache_key,
            "duration_ms": round(self.duration_ms, 3),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CASResult:
        return cls(
            status=CASStatus(payload["status"]),
            basis=CASBasis(payload["basis"]),
            evidence_grade=CASEvidenceGrade(
                payload.get("evidence_grade") or CASEvidenceGrade.NONE
            ),
            assumptions=list(payload.get("assumptions") or []),
            witness=payload.get("witness"),
            lhs_value=payload.get("lhs_value"),
            rhs_value=payload.get("rhs_value"),
            observation=dict(payload.get("observation") or {}),
            reason=str(payload.get("reason") or ""),
            reason_code=str(payload.get("reason_code") or ""),
            seed=payload.get("seed"),
            sympy_version=str(payload.get("sympy_version") or ""),
            policy_version=str(payload.get("policy_version") or ""),
            cache_key=str(payload.get("cache_key") or ""),
            duration_ms=float(payload.get("duration_ms") or 0.0),
        )


@dataclass(frozen=True)
class TranslationFailure:
    """Machine-readable explanation for a rejected semantic unit."""

    code: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


class CASTranslationError(ValueError):
    """Raised when a Semantic Unit falls outside the declared CAS subset."""

    def __init__(self, failure: TranslationFailure):
        self.failure = failure
        super().__init__(f"{failure.code} at {failure.path}: {failure.detail}")


class CASCapabilityUnavailable(RuntimeError):
    """Raised internally when the optional SymPy dependency is absent."""
