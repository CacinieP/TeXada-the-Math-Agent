"""Conservative admission check for explicit computation requests.

This is a product boundary, not a complete intent classifier. Ambiguous formula
descriptions remain candidates requiring review; no semantic correctness claim
is inferred from passing this check.
"""
from __future__ import annotations

import re

SCOPE_MESSAGE = (
    "TeXada 仅支持公式识别、转写和排版，不提供计算、化简、求解或证明。"
    "请描述要输入的公式；例如“输入 7+5”，或“输入 f(x) 的导数记号”。 "
    "TeXada transcribes and typesets formulas; calculation, simplification, "
    "solving and proofs are outside its scope. Describe the notation to enter."
)


class ComputationOutsideScope(ValueError):
    """An explicit request asks the product to compute rather than transcribe."""


def requests_computation(text: str) -> bool:
    # Literal labels/code are content to transcribe, not user instructions.
    instruction = re.sub(r'```[\s\S]*?```|`[^`]*`|"[^"\n]*"|“[^”]*”|「[^」]*」', '', text)
    verbs = r"计算|求值|化简|因式分解|解方程|求解|求导|求积分|求极限|证明|算出|算一下"
    instruction = re.sub(
        rf"(?:不需要|无需|不用|不要|不必|禁止|不做|不)(?:进行)?(?:{verbs})", '', instruction,
    )
    instruction = re.sub(
        r"\b(?:do not|don't|without|no need to)\s+"
        r"(?:compute|calculate|evaluate|solve|simplify|factor(?:ize)?|differentiate|integrate|prove)\b",
        '', instruction, flags=re.I,
    )
    if re.search(rf"(?:{verbs})(?!符号|记号|二字|这两个字|字样)", instruction):
        return True
    if re.search(r"分解[^，。；\n]{0,20}因式|展开(?:括号|多项式)", instruction):
        return True
    if re.search(r"求[^，。；\n]{1,60}(?:的导数|的积分|的值|的解|的极限)", instruction):
        return True
    return bool(re.search(
        r"(?:^|[.!?;\n]|\b(?:please|and|then|to|you))\s*"
        r"(?:compute|calculate|evaluate|solve|simplify|factor(?:ize)?|differentiate|integrate|prove)\b"
        r"(?!\s+(?:symbol|notation|label|word)\b)", instruction, flags=re.I,
    ))


def require_transcription(text: str) -> None:
    if requests_computation(text):
        raise ComputationOutsideScope(SCOPE_MESSAGE)
