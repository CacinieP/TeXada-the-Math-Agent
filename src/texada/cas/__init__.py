"""Optional, boundary-declared computer algebra support for TeXada."""

from texada.cas.checker import AlgebraChecker, build_cache_key
from texada.cas.model import (
    CASBasis,
    CASEvidenceGrade,
    CASResult,
    CASStatus,
    CASTranslationError,
    TranslationFailure,
)
from texada.cas.translator import SemanticSymPyTranslator, TranslatedExpression
from texada.cas.worker import (
    CASWorker,
    CASWorkerError,
    CASWorkerMemoryExceeded,
    CASWorkerTimeout,
)

__all__ = [
    "AlgebraChecker",
    "CASBasis",
    "CASEvidenceGrade",
    "CASResult",
    "CASStatus",
    "CASTranslationError",
    "CASWorker",
    "CASWorkerError",
    "CASWorkerMemoryExceeded",
    "CASWorkerTimeout",
    "SemanticSymPyTranslator",
    "TranslatedExpression",
    "TranslationFailure",
    "build_cache_key",
]
