"""Explicit data directories never inherit another installation's settings."""
import json

from texada.config import TeXadaConfig, save_config_updates


def legacy_config(monkeypatch, tmp_path):
    path = tmp_path / "normal" / "config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"backend": "openai_compatible",
                                "openai_api_key": "synthetic-private-key",
                                "openai_base_url": "https://example.invalid/v1"}))
    monkeypatch.setitem(TeXadaConfig.model_config, "json_file", str(path))
    return path


def test_environment_data_directory_does_not_read_legacy_provider(monkeypatch, tmp_path):
    original = legacy_config(monkeypatch, tmp_path)
    before = original.read_bytes()
    selected = tmp_path / "isolated"
    monkeypatch.setenv("TEXADA_DATA_DIR", str(selected))
    config = TeXadaConfig()
    assert config.data_dir == selected
    assert config.backend == "llama_server"
    assert config.openai_api_key == ""
    saved = save_config_updates({"ui_language": "en"})
    assert saved.data_dir == selected
    assert TeXadaConfig().ui_language == "en"
    assert json.loads((selected / "config.json").read_text()) == {"ui_language": "en"}
    assert original.read_bytes() == before


def test_explicit_data_directory_wins_and_reloads_its_own_settings(monkeypatch, tmp_path):
    legacy_config(monkeypatch, tmp_path)
    environment = tmp_path / "environment"
    environment.mkdir()
    (environment / "config.json").write_text(json.dumps({"ui_language": "zh"}))
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "config.json").write_text(json.dumps({"ui_language": "en"}))
    monkeypatch.setenv("TEXADA_DATA_DIR", str(environment))
    config = TeXadaConfig(data_dir=selected)
    assert config.data_dir == selected
    assert config.ui_language == "en"
    assert config.openai_api_key == ""


def test_default_config_source_is_preserved_without_an_isolated_directory(monkeypatch, tmp_path):
    legacy_config(monkeypatch, tmp_path)
    config = TeXadaConfig()
    assert config.backend == "openai_compatible"
    assert config.openai_api_key == "synthetic-private-key"
