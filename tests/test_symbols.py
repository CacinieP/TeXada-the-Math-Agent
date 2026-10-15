"""Test SymbolEngine — zero-model, deterministic pre-translation."""
from texada.core.symbols import SymbolEngine


def test_basic_translate():
    eng = SymbolEngine()
    result = eng.pre_translate("二重积分 f(x,y) 在区域 D 上")
    assert "\\iint" in result
    assert "f(x,y)" in result


def test_long_match_priority():
    """三重积分 should match before 积分."""
    eng = SymbolEngine()
    result = eng.pre_translate("三重积分")
    assert result == "\\iiint"
    # A partial match used to leave an extra Chinese character ("\\div以")
    # in the planner's authoritative preprocessed prompt.
    assert eng.pre_translate("a 与 b 的和除以 c") == r"a 与 b 的和\div c"
    assert eng.pre_translate(r"a \div c") == r"a \div c"


def test_multiple_terms():
    eng = SymbolEngine()
    result = eng.pre_translate("属于不属于")
    assert "\\in" in result
    assert "\\notin" in result


def test_no_double_translation():
    """Already-translated symbols should not be re-translated."""
    eng = SymbolEngine()
    result = eng.pre_translate("\\iint f(x,y)")
    assert result == "\\iint f(x,y)"  # unchanged


def test_greek_letters():
    eng = SymbolEngine()
    result = eng.pre_translate("阿尔法贝塔")
    assert "\\alpha" in result
    assert "\\beta" in result


def test_decorations():
    eng = SymbolEngine()
    result = eng.pre_translate("向量帽子波浪")
    assert "\\vec" in result
    assert "\\hat" in result
    assert "\\tilde" in result


def test_named_concepts_are_not_corrupted_by_partial_symbol_replacement():
    engine = SymbolEngine()

    assert engine.pre_translate("导数定义") == "导数定义"
    assert engine.pre_translate("极限定义式") == "极限定义式"
    assert engine.pre_translate("概率密度函数") == "概率密度函数"


def test_factorial_is_one_term_and_does_not_become_multiplication():
    engine = SymbolEngine()
    assert engine.translate("阶乘") == "!"
    assert engine.pre_translate("n 的阶乘") == "n 的!"
    assert engine.pre_translate("5 的阶乘") == "5 的!"  # Not the evaluated value.
    assert engine.pre_translate("n 的阶乘乘 m") == r"n 的!\times m"
    assert engine.pre_translate("a 乘 b") == r"a \times b"
    assert engine.pre_translate(r"n! + n\!") == r"n! + n\!"


def test_other_factorial_concepts_are_not_partially_translated():
    engine = SymbolEngine()
    for term in ("双阶乘", "升阶乘", "降阶乘", "多重阶乘", "阶乘函数", "阶乘定义"):
        assert engine.pre_translate(term) == term, term
    assert engine.pre_translate("n 的阶乘与 n 的双阶乘") == "n 的!与 n 的双阶乘"


def test_vector_two_norm_pretranslation_binds_the_explicit_operand():
    engine = SymbolEngine()
    assert engine.pre_translate("向量 x 的二范数") == r"\lVert x\rVert_2"
    assert engine.pre_translate(" 向量 v 的二范数。 ") == r"\lVert v\rVert_2"
    assert engine.pre_translate(r"\lVert x\rVert_2") == r"\lVert x\rVert_2"


def test_unbound_norm_term_does_not_produce_a_placeholder_formula():
    engine = SymbolEngine()
    assert engine.translate("范数") is None
    assert engine.pre_translate("范数") == "范数"
    assert engine.pre_translate("范数定义") == "范数定义"
    assert engine.translate("范数符号") == r"\|"
    assert engine.pre_translate("范数符号") == r"\|"
    for description in (
        "向量 x+y 的二范数", "向量 xy 的二范数", "向量 x 的一范数",
        "不要写向量 x 的二范数", "计算向量 x 的二范数", "向量 x 的二范数.png",
    ):
        preprocessed = engine.pre_translate(description)
        assert "范数" in preprocessed, description
        assert r"\cdot" not in preprocessed, description
        assert r"\lVert" not in preprocessed, description
        assert r"\|" not in preprocessed, description
