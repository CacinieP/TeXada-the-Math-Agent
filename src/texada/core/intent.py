"""Intent Classifier — zero-model regex-based intent detection."""
from __future__ import annotations

import re

from texada.types import IntentResult

# Ordered by specificity — first match wins
INTENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("integral",    re.compile(r"(三重积分|二重积分|线积分|积分|∮|∬|∭|∫|integral|integrate)", re.I)),
    ("derivative",  re.compile(r"(偏导|梯度|∇|微分|导数|derivative|diff|d/dx)", re.I)),
    ("sum",         re.compile(r"(连乘|求和|级数|∏|∑|sum|series|product)", re.I)),
    ("limit",       re.compile(r"(极限|lim|limit|趋近|→)", re.I)),
    ("matrix",      re.compile(r"(行列式|det|特征值|eigen|矩阵|matrix)", re.I)),
    ("probability", re.compile(r"(方差|协方差|期望|分布|正态|泊松|概率|Var|Cov|E\[|P\(|probability)", re.I)),
    ("set",         re.compile(r"(补集|真子集|子集|包含|交集|∩|并集|∪|∈|集合|subset)", re.I)),
    ("logic",       re.compile(r"(等价|⟹|蕴含|⇒|∀|∃|forall|implies|logic)", re.I)),
    ("trig",        re.compile(r"(正切|余弦|正弦|tan|cos|sin|trig)", re.I)),
    ("fraction",    re.compile(r"(分式|分数线|frac)", re.I)),
    ("generic",     re.compile(r".*")),
]


class IntentClassifier:
    """Regex-based intent classification — zero model calls, <1ms."""

    def classify(self, text: str) -> IntentResult:
        for intent, pattern in INTENT_PATTERNS:
            if pattern.search(text):
                confidence = 0.9 if intent != "generic" else 0.3
                return IntentResult(intent=intent, confidence=confidence)
        return IntentResult(intent="generic", confidence=0.3)