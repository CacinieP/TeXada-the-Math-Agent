"""TeXada configuration — Pydantic Settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

TEXADA_HOME = Path.home() / ".texada"
CONFIG_FILE = TEXADA_HOME / "config.json"

SAVED_CONFIG_FIELDS = frozenset({
    "backend",
    "ollama_host",
    "model_name",
    "vision_model_name",
    "openai_base_url",
    "openai_api_key",
    "openai_model_name",
    "openai_vision_model_name",
    "temperature",
    "max_tokens",
    "default_render_mode",
    "delimiter",
    "ui_language",
    "ui_zoom",
    "inference_timeout_seconds",
    "api_request_timeout_seconds",
    "agent_max_steps",
    "agent_token_budget",
    "run_log_max_days",
    "run_log_max_items",
})


class TeXadaConfig(BaseSettings):
    """All TeXada settings, loaded from ~/.texada/config.json + env vars.

    TeXada defaults to local Ollama MiniCPM models and can be switched to any
    OpenAI-compatible endpoint. Both paths speak the standard OpenAI chat API;
    text and vision (OCR) requests use separate configurable model names.
    """

    model_config = SettingsConfigDict(
        json_file=str(TEXADA_HOME / "config.json"),
        json_file_encoding="utf-8",
        env_prefix="TEXADA_",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # ── Ollama backend (MiniCPM) ──
    backend: Literal["ollama", "openai_compatible"] = "ollama"
    ollama_host: str = "http://localhost:11434"
    model_name: str = "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"  # Text: MiniCPM5-1B
    vision_model_name: str = "openbmb/minicpm-v4.6:latest"  # MiniCPM-V 4.6 OCR
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model_name: str = ""
    openai_vision_model_name: str = ""
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=64, le=32768)
    inference_timeout_seconds: float = Field(default=90.0, gt=0.0, le=600.0)
    api_request_timeout_seconds: float = Field(default=240.0, gt=0.0, le=900.0)

    # ── Agent Runtime ──
    agent_max_steps: int = Field(default=3, ge=1, le=8)
    # Run-level cumulative planner-token budget. Checked before each model
    # call; exhaustion halts the loop and flows into the deterministic
    # fallback ladder instead of silently continuing. Zero disables it.
    agent_token_budget: int = Field(default=32768, ge=0)
    # Wall-clock budget for one TeX tool call; a pathological input cannot
    # pin the service beyond this bound.
    tool_timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)

    # ── Render ──
    default_render_mode: Literal["katex", "latex"] = "katex"
    delimiter: Literal["$$", "$", "\\[", "\\("] = "$$"
    katex_enabled: bool = True
    latex_highlight_enabled: bool = True
    ui_language: Literal["zh", "en"] = "zh"
    ui_zoom: float = 1.0

    # ── Server ──
    api_host: str = "127.0.0.1"
    api_port: int = 18732
    api_allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    ]
    max_ocr_bytes: int = 5 * 1024 * 1024
    allowed_image_mime_types: list[str] = [
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/bmp",
        "image/tiff",
    ]

    # ── Hotkeys ──
    hotkey_wake: str = "cmd+alt+t"
    hotkey_switch_mode: str = "cmd+k"

    # ── History ──
    history_max_days: int = 30
    history_max_items: int = 1000

    # ── Request-level run logs ──
    # Zero means unlimited. Every run is kept unless the user configures a cap.
    run_log_max_days: int = Field(default=0, ge=0)
    run_log_max_items: int = Field(default=0, ge=0)

    # ── Paths ──
    data_dir: Path = TEXADA_HOME

    @staticmethod
    def _normalize_url(value: object) -> str:
        raw = str(value or "").strip().rstrip("/")
        if not raw:
            return ""
        if "://" not in raw:
            raw = f"http://{raw}"
        return raw

    @field_validator("ollama_host", mode="before")
    @classmethod
    def normalize_ollama_host(cls, value: object) -> str:
        raw = cls._normalize_url(value)
        if raw.endswith("/v1"):
            raw = raw[:-3].rstrip("/")
        return raw

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: object) -> str:
        return cls._normalize_url(value)

    @field_validator("ui_zoom", mode="before")
    @classmethod
    def clamp_ui_zoom(cls, value: object) -> float:
        try:
            zoom = float(value)
        except (TypeError, ValueError):
            return 1.0
        return min(1.4, max(0.8, zoom))

    def ensure_dirs(self) -> None:
        """Create ~/.texada and subdirs if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def uses_openai_compatible(self) -> bool:
        return self.backend == "openai_compatible"

    @property
    def active_base_url(self) -> str:
        if self.uses_openai_compatible:
            return self.openai_base_url.rstrip("/")
        return f"{self.ollama_host.rstrip('/')}/v1"

    @property
    def active_api_key(self) -> str:
        if self.uses_openai_compatible:
            return self.openai_api_key
        return "ollama"

    @property
    def active_model_name(self) -> str:
        if self.uses_openai_compatible:
            return self.openai_model_name
        return self.model_name

    @property
    def active_vision_model_name(self) -> str:
        if self.uses_openai_compatible:
            return self.openai_vision_model_name or self.openai_model_name
        return self.vision_model_name

    @property
    def api_base_url(self) -> str:
        """Browser-facing URL for the local TeXada API."""
        host = self.api_host.strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.api_port}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        _ = (dotenv_settings, file_secret_settings)
        return (
            init_settings,
            env_settings,
            JsonConfigSettingsSource(settings_cls),
        )


def load_config() -> TeXadaConfig:
    """Load configuration."""
    config = TeXadaConfig()
    config.ensure_dirs()
    return config


def _prepare_config_updates(
    updates: dict,
    data_dir: Path | None = None,
) -> tuple[Path, dict, TeXadaConfig]:
    target_dir = data_dir or TEXADA_HOME
    config_file = target_dir / "config.json"
    existing: dict = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    for key, value in updates.items():
        if key in SAVED_CONFIG_FIELDS:
            existing[key] = value
    validated = TeXadaConfig(data_dir=target_dir, **existing)
    return config_file, existing, validated


def validate_config_updates(
    updates: dict,
    data_dir: Path | None = None,
) -> TeXadaConfig:
    """Validate prospective saved settings without changing the filesystem."""
    return _prepare_config_updates(updates, data_dir)[2]


def save_config_updates(updates: dict, data_dir: Path | None = None) -> TeXadaConfig:
    """Validate first, then atomically persist supported user settings."""
    config_file, existing, validated = _prepare_config_updates(updates, data_dir)
    target_dir = config_file.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = config_file.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(config_file)
    try:
        os.chmod(config_file, 0o600)
    except OSError:
        pass
    return validated
