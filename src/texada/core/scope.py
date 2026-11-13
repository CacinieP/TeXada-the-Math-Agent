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
    verbs = r"计算|求值|化简|因式分解|解方程|求解|求导|求积分|求极限|推导|证明|算出|算一下"
    instruction = re.sub(
        rf"(?:不需要|无需|不用|不要|不必|禁止|不做|不)(?:进行)?(?:{verbs})", '', instruction,
    )
    instruction = re.sub(
        r"\b(?:do not|don't|without|no need to)\s+"
        r"(?:compute|calculate|evaluate|solve|simplify|factor(?:ize)?|differentiate|integrate|prove)\b",
        '', instruction, flags=re.I,
    )
    # 名词化的"求导法则 / 求积分公式 / 极限表"是要排版的对象，不是让我动手算。
    # 只剥离这些固定搭配，剩下的动词仍照常判定：'计算这个求导公式' 仍会被拒绝。
    instruction = re.sub(r"(?:求导|积分|极限)(?:的)?(?:法则|公式|规则|表)", '', instruction)
    if re.search(rf"(?:{verbs})(?!符号|记号|二字|这两个字|字样)", instruction):
        return True
    if re.search(r"等于多少|结果是多少|答案是(?:多少|什么)|解(?:这个|一下)?方程", instruction):
        return True
    # 口语化的求值请求：真实语料里 "2+3 等于几" / "3的平方加上4的平方是多少" /
    # "1加2加3一直加到100的和" 都会绕过上面的动词表（eval/real_world_set.yaml
    # 的 no-solving 类目就是这批输入）。
    if re.search(r"等于几|是几|是多少|几多", instruction):
        return True
    if re.search(r"加到\s*\d+\s*的?(?:和|积|乘积|结果)", instruction):
        return True
    if re.search(
        r"\b(?:what is|how much is)\s+(?:the\s+)?"
        r"(?:derivative of|integral of|[0-9]+\s*[+*/-])", instruction, flags=re.I,
    ):
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


def transcription_description(text: str) -> str:
    """Remove presentation wrappers only; callers must still match whole patterns."""
    text = text.strip().rstrip('。.!！?？')
    text = re.sub(r'^(?:请)?(?:帮我)?(?:输入|排版|转写)\s*', '', text)
    return re.sub(r'(?:的)?(?:记号|符号)$', '', text).strip()
