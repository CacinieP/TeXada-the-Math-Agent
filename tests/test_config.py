"""Configuration contracts for TeXada's two-model product boundary."""

import json
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from texada.config import (
    SAVED_CONFIG_FIELDS,
    TeXadaConfig,
    save_config_updates,
)

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_synchronized_across_python_node_and_tauri():
    python_version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    package_version = json.loads(
        (ROOT / "package.json").read_text(encoding="utf-8")
    )["version"]
    package_lock_version = json.loads(
        (ROOT / "package-lock.json").read_text(encoding="utf-8")
    )["version"]
    cargo_version = tomllib.loads(
        (ROOT / "tauri-shell/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    )["package"]["version"]
    tauri_version = json.loads(
        (ROOT / "tauri-shell/src-tauri/tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )["version"]
    frontend = (ROOT / "tauri-shell/src/index.html").read_text(encoding="utf-8")

    assert {
        python_version,
        package_version,
        package_lock_version,
        cargo_version,
        tauri_version,
    } == {"0.3.0"}
    assert f"v{python_version}" in frontend


def test_default_product_has_exactly_two_minicpm_model_roles():
    fields = TeXadaConfig.model_fields

    assert fields["model_name"].default == "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"
    assert fields["vision_model_name"].default == "openbmb/minicpm-v4.6:latest"
    assert "tex2tex_model_path" not in fields
    assert "tex2tex_max_new_tokens" not in fields


def test_saved_settings_do_not_expose_repair_model_configuration():
    assert "tex2tex_model_path" not in SAVED_CONFIG_FIELDS
    assert "tex2tex_max_new_tokens" not in SAVED_CONFIG_FIELDS


def test_run_logs_are_unlimited_by_default_but_caps_remain_configurable():
    fields = TeXadaConfig.model_fields

    assert fields["run_log_max_days"].default == 0
    assert fields["run_log_max_items"].default == 0
    assert {"run_log_max_days", "run_log_max_items"} <= SAVED_CONFIG_FIELDS


def test_invalid_operational_settings_are_rejected():
    for updates in (
        {"backend": "unsupported"},
        {"temperature": 2.1},
        {"max_tokens": 0},
        {"agent_max_steps": 0},
        {"run_log_max_items": -1},
        {"default_render_mode": "html"},
    ):
        with pytest.raises(ValidationError):
            TeXadaConfig(**updates)


def test_invalid_config_update_does_not_overwrite_existing_file(tmp_path):
    save_config_updates({"ui_language": "en"}, data_dir=tmp_path)
    config_path = tmp_path / "config.json"
    original = config_path.read_text(encoding="utf-8")

    with pytest.raises(ValidationError):
        save_config_updates({"temperature": 99}, data_dir=tmp_path)

    assert config_path.read_text(encoding="utf-8") == original
