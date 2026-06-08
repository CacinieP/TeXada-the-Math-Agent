"""Test IntentClassifier — zero-model, fast regex-based."""
from texada.core.intent import IntentClassifier


def test_integral():
    cls = IntentClassifier()
    r = cls.classify("二重积分 f(x,y) 在区域 D 上")
    assert r.intent == "integral"
    assert r.confidence == 0.9


def test_derivative():
    cls = IntentClassifier()
    r = cls.classify("f(x)关于x的偏导数")
    assert r.intent == "derivative"


def test_sum():
    cls = IntentClassifier()
    r = cls.classify("从i=1到n的x_i求和")
    assert r.intent == "sum"


def test_limit():
    cls = IntentClassifier()
    r = cls.classify("x趋近于0时sin(x)/x的极限")
    assert r.intent == "limit"


def test_matrix():
    cls = IntentClassifier()
    r = cls.classify("矩阵A的行列式")
    assert r.intent == "matrix"


def test_probability():
    cls = IntentClassifier()
    r = cls.classify("正态分布N(μ,σ²)")
    assert r.intent == "probability"


def test_set():
    cls = IntentClassifier()
    r = cls.classify("集合A属于B")
    assert r.intent == "set"


def test_generic():
    cls = IntentClassifier()
    r = cls.classify("随便一句话")
    assert r.intent == "generic"
    assert r.confidence == 0.3


def test_double_integral_priority():
    """三重积分/二重积分 should match before 积分."""
    cls = IntentClassifier()
    r = cls.classify("三重积分 f 在 V 上")
    assert r.intent == "integral"