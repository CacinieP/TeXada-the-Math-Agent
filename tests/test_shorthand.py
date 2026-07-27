"""Test ShorthandStore — built-in and user-defined shorthands."""
import pytest

from texada.config import TeXadaConfig
from texada.store.shorthand import ShorthandStore


def test_shorthand_defaults(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    store = ShorthandStore(config)

    # Check default shorthands are loaded
    assert store.has("euler")
    assert store.lookup("euler") == "e^{i\\pi}+1=0"
    assert store.lookup("pyth") == "a^2+b^2=c^2"


def test_shorthand_add_delete(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    store = ShorthandStore(config)

    # Test adding shorthand
    store.add("foo", "bar")
    assert store.has("foo")
    assert store.lookup("foo") == "bar"

    # Test persistence (re-load from file)
    store2 = ShorthandStore(config)
    assert store2.has("foo")
    assert store2.lookup("foo") == "bar"

    # Test deleting shorthand
    assert store2.delete("foo")
    assert not store2.has("foo")

    # Cannot delete built-in shorthand
    assert not store2.delete("euler")
    assert store2.has("euler")


def test_shorthand_list_all(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    store = ShorthandStore(config)

    # Test listing all
    all_items = store.list_all()
    assert len(all_items) > 10

    # Test querying
    query_items = store.list_all("euler")
    assert len(query_items) == 2  # euler and euler-g
    keys = [item[0] for item in query_items]
    assert "euler" in keys
    assert "euler-g" in keys


def test_shorthand_import_exports_user_defined_only(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    store = ShorthandStore(config)

    result = store.import_many({
        "custom": "x^2",
        "euler": "should-not-overwrite-built-in",
        "": "empty-key",
    })

    assert result == {"imported": 1, "skipped": 2, "cleared": 0}
    assert store.lookup("custom") == "x^2"
    assert store.lookup("euler") == "e^{i\\pi}+1=0"
    assert store.list_user_defined() == {"custom": "x^2"}


def test_shorthand_rejects_builtin_replacement_and_non_formula_content(tmp_path):
    store = ShorthandStore(TeXadaConfig(data_dir=tmp_path))

    with pytest.raises(ValueError, match="cannot be replaced"):
        store.add("euler", "x")
    with pytest.raises(ValueError):
        store.add("prose", "这不是一个公式")

    assert store.lookup("euler") == "e^{i\\pi}+1=0"
    assert not store.has("prose")
