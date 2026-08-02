"""Configuration contracts for TeXada's two-model product boundary."""

import json
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from texada import __version__
from texada.api import _app_version
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
    package_lock = json.loads(
        (ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    package_lock_version = package_lock["version"]
    package_lock_root_version = package_lock["packages"][""]["version"]
    cargo_version = tomllib.loads(
        (ROOT / "tauri-shell/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    )["package"]["version"]
    cargo_lock = tomllib.loads(
        (ROOT / "tauri-shell/src-tauri/Cargo.lock").read_text(encoding="utf-8")
    )
    cargo_lock_version = next(
        package["version"]
        for package in cargo_lock["package"]
        if package["name"] == "texada-shell"
    )
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    uv_lock_version = next(
        package["version"]
        for package in uv_lock["package"]
        if package["name"] == "texada"
    )
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
        package_lock_root_version,
        cargo_version,
        cargo_lock_version,
        tauri_version,
        uv_lock_version,
        __version__,
        _app_version(),
    } == {"0.3.6"}
    assert f"v{python_version}" in frontend


def test_license_is_synchronized_as_agpl_v3_or_later():
    expected = "AGPL-3.0-or-later"
    python_license = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["license"]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    cargo_license = tomllib.loads(
        (ROOT / "tauri-shell/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    )["package"]["license"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert {
        python_license,
        package["license"],
        package_lock["packages"][""]["license"],
        cargo_license,
    } == {expected}
    assert "license-AGPL--3.0--or--later-blue" in readme
    assert "`AGPL-3.0-or-later`" in readme
    assert "assets/texada-hero-agpl.png" in readme
    assert (ROOT / "assets/texada-hero-agpl.png").is_file()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text


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


def test_defaults_allow_slow_local_vision_inference_and_dev_origin():
    fields = TeXadaConfig.model_fields

    assert fields["inference_timeout_seconds"].default == 90.0
    assert fields["api_request_timeout_seconds"].default == 240.0
    assert "http://127.0.0.1:1420" in fields["api_allowed_origins"].default


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
