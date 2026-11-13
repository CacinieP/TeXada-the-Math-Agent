"""Tests for the "transcribe, don't evaluate" guard (issue #78)."""

import pytest

from texada.core.evaluation_guard import is_arithmetic_input, suspects_evaluation

# (input, latex, expected)
CASES = [
    # 真实失败样本：模型算出了结果
    ("2+3 等于几", "2+3=5", True),
    ("3的平方加上4的平方是多少", "9+16=25", True),
    ("1加2加3一直加到100的和", r"\sum_{k=1}^{100}k=\frac{100\cdot101}{2}=5050", True),
    ("sin x 从 0 到 π 的定积分等于多少", r"\int_0^{\pi}\sin x\,dx=2", True),
    ("x 趋于 0 时 (1+x) 的 1/x 次方", r"\lim_{x\to0}(1+x)^{\frac{1}{x}}=e", True),
    ("2+3 等于几", "2+3=5.0", True),
    # 合法：等号右边不是"用户没写过的常数"
    ("解方程 x^2-5x+6=0", "x^2-5x+6=0", False),
    ("证明 e 的 iπ 次方加 1 等于 0", r"e^{i\pi}+1=0", False),
    ("贝叶斯公式", r"P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}", False),
    ("格林公式", r"\oint_L P\,dx+Q\,dy=\iint_D\left(Q_x-P_y\right)dx\,dy", False),
    ("x 等于 5", "x=5", False),
    ("二项分布期望", r"E(X)=np", False),
    ("2+3 等于几", "2+3", False),
    ("", "", False),
]


@pytest.mark.parametrize(("user_input", "latex", "expected"), CASES)
def test_suspects_evaluation(user_input, latex, expected):
    assert suspects_evaluation(user_input, latex) is expected


def test_arithmetic_input_detection():
    assert is_arithmetic_input("2+3")
    assert is_arithmetic_input(" 1/2 + 3 ")
    assert not is_arithmetic_input("2+3 等于几")
    assert not is_arithmetic_input("x^2-5x+6=0")
    assert not is_arithmetic_input("")


def test_guard_does_not_flag_fraction_that_matches_input():
    # 用户写了 1/2 与 3/2，输出里的 0.5 仍然是"算出来的"，应被标记
    assert suspects_evaluation("二分之一加一", r"\frac{1}{2}+1=1.5")
