"""Public orchestration layer for conservative algebraic checks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from texada.cas.model import (
    CASBasis,
    CASCapabilityUnavailable,
    CASEvidenceGrade,
    CASResult,
    CASStatus,
    CASTranslationError,
)
from texada.cas.policy import POLICY_VERSION
from texada.cas.translator import SemanticSymPyTranslator
from texada.cas.worker import (
    CASWorker,
    CASWorkerError,
    CASWorkerMemoryExceeded,
    CASWorkerTimeout,
)
from texada.semantic.model import SemanticDocument


class AlgebraChecker:
    """Translate trusted semantic trees, then compare them in a worker process."""

    def __init__(
        self,
        *,
        worker: CASWorker | None = None,
        timeout_ms: int = 1000,
        seed: int = 0,
        max_rss_bytes: int | None = 512 * 1024**2,
    ):
        self.worker = worker or CASWorker(
            timeout_ms=timeout_ms,
            max_rss_bytes=max_rss_bytes,
        )
        self.timeout_ms = timeout_ms
        self.seed = _validated_seed(seed)

    @staticmethod
    def available() -> bool:
        return all(
            importlib.util.find_spec(package) is not None
            for package in ("sympy", "psutil")
        )

    def check(
        self,
        lhs: SemanticDocument,
        rhs: SemanticDocument,
        *,
        assumptions: dict[str, dict[str, bool]] | None = None,
        timeout_ms: int | None = None,
        seed: int | None = None,
    ) -> CASResult:
        started = time.monotonic()
        selected_seed = self.seed if seed is None else _validated_seed(seed)
        sympy_version = self._package_version("sympy")
        cache_key = build_cache_key(
            lhs,
            rhs,
            assumptions=assumptions,
            sympy_version=sympy_version,
            policy_version=POLICY_VERSION,
            seed=selected_seed,
        )
        if not self.available():
            missing = [
                package
                for package in ("sympy", "psutil")
                if importlib.util.find_spec(package) is None
            ]
            return self._timed(
                CASResult(
                    status=CASStatus.UNAVAILABLE,
                    basis=CASBasis.CAPABILITY_UNAVAILABLE,
                    reason=(
                        "CAS dependencies are unavailable: "
                        f"{', '.join(missing) or 'availability check failed'}; "
                        "install TeXada with the 'cas' extra"
                    ),
                    reason_code="cas_dependencies_unavailable",
                    seed=selected_seed,
                    sympy_version=sympy_version,
                    policy_version=POLICY_VERSION,
                    cache_key=cache_key,
                ),
                started,
            )

        translator = SemanticSymPyTranslator(assumptions=assumptions)
        try:
            lhs_expression = translator.translate_document(lhs)
            rhs_expression = translator.translate_document(rhs)
        except CASTranslationError as exc:
            return self._timed(
                CASResult(
                    status=CASStatus.UNSUPPORTED,
                    basis=CASBasis.UNSUPPORTED_SEMANTIC_UNIT,
                    evidence_grade=CASEvidenceGrade.NONE,
                    assumptions=translator.assumption_labels,
                    observation={"translation_failure": exc.failure.to_dict()},
                    reason=exc.failure.detail,
                    reason_code=exc.failure.code,
                    seed=selected_seed,
                    sympy_version=sympy_version,
                    policy_version=POLICY_VERSION,
                    cache_key=cache_key,
                ),
                started,
            )
        except CASCapabilityUnavailable as exc:
            return self._timed(
                CASResult(
                    status=CASStatus.UNAVAILABLE,
                    basis=CASBasis.CAPABILITY_UNAVAILABLE,
                    reason=str(exc),
                    reason_code="sympy_not_installed",
                    seed=selected_seed,
                    sympy_version=sympy_version,
                    policy_version=POLICY_VERSION,
                    cache_key=cache_key,
                ),
                started,
            )

        try:
            result = self.worker.compare(
                lhs_expression.expression,
                rhs_expression.expression,
                assumptions=translator.assumption_labels,
                timeout_ms=timeout_ms or self.timeout_ms,
                seed=selected_seed,
            )
        except CASWorkerTimeout as exc:
            result = CASResult(
                status=CASStatus.TIMEOUT,
                basis=CASBasis.WORKER_TIMEOUT,
                evidence_grade=CASEvidenceGrade.OBSERVATION,
                assumptions=translator.assumption_labels,
                reason=str(exc),
                reason_code="worker_timeout",
            )
        except CASWorkerMemoryExceeded as exc:
            result = CASResult(
                status=CASStatus.UNKNOWN,
                basis=CASBasis.WORKER_MEMORY_LIMIT,
                evidence_grade=CASEvidenceGrade.OBSERVATION,
                assumptions=translator.assumption_labels,
                observation={
                    "peak_rss_bytes": exc.peak_rss_bytes,
                    "rss_limit_bytes": exc.limit_bytes,
                    "rss_monitor": "parent_pid_psutil",
                },
                reason=str(exc),
                reason_code="worker_memory_limit",
            )
        except CASWorkerError as exc:
            result = CASResult(
                status=CASStatus.UNKNOWN,
                basis=CASBasis.WORKER_ERROR,
                evidence_grade=CASEvidenceGrade.OBSERVATION,
                assumptions=translator.assumption_labels,
                reason=str(exc),
                reason_code="worker_error",
            )
        result.observation.setdefault("lhs_srepr", lhs_expression.srepr)
        result.observation.setdefault("rhs_srepr", rhs_expression.srepr)
        result.seed = selected_seed
        result.sympy_version = result.sympy_version or sympy_version
        result.policy_version = result.policy_version or POLICY_VERSION
        result.cache_key = cache_key
        return self._timed(result, started)

    def close(self) -> None:
        self.worker.close()

    def __enter__(self) -> AlgebraChecker:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @staticmethod
    def _timed(result: CASResult, started: float) -> CASResult:
        result.duration_ms = (time.monotonic() - started) * 1000
        return result

    @staticmethod
    def _package_version(package: str) -> str:
        try:
            return version(package)
        except PackageNotFoundError:
            return ""


def build_cache_key(
    lhs: SemanticDocument,
    rhs: SemanticDocument,
    *,
    assumptions: dict[str, dict[str, bool]] | None,
    sympy_version: str,
    policy_version: str,
    seed: int,
) -> str:
    """Build an ordered, reproducible cache key for a CAS comparison."""
    canonical_assumptions = {
        symbol: {
            name: value
            for name, value in sorted(values.items())
        }
        for symbol, values in sorted((assumptions or {}).items())
    }
    payload = {
        "fingerprint_a": lhs.root.fingerprint(),
        "fingerprint_b": rhs.root.fingerprint(),
        "assumptions": canonical_assumptions,
        "sympy_version": sympy_version,
        "policy_version": policy_version,
        "seed": seed,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validated_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("CAS seed must be an integer")
    return seed
