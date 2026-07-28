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
