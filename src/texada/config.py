"""TeXada configuration — Pydantic Settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

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
    "inference_timeout_seconds",
    "api_request_timeout_seconds",
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
    backend: str = "ollama"  # "ollama" | "openai_compatible"
    ollama_host: str = "http://localhost:11434"
    model_name: str = "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"  # Text: MiniCPM5-1B
    vision_model_name: str = "openbmb/minicpm-v4.6:latest"     # Vision: MiniCPM-V 4.6 (OCR)
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model_name: str = ""
    openai_vision_model_name: str = ""
    temperature: float = 0.1
    max_tokens: int = 2048  # MiniCPM5 is a reasoning model — CoT needs headroom
    inference_timeout_seconds: float = 45.0
    api_request_timeout_seconds: float = 120.0

    # ── Render ──
    default_render_mode: str = "katex"   # "katex" | "latex"
    delimiter: str = "$$"                 # "$$" | "\[" | "$"
    katex_enabled: bool = True
    latex_highlight_enabled: bool = True
    ui_language: str = "zh"  # "zh" | "en"

    # ── Server ──
    api_host: str = "127.0.0.1"
    api_port: int = 18732
    api_allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
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

    # ── Paths ──
    data_dir: Path = TEXADA_HOME

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


def save_config_updates(updates: dict, data_dir: Path | None = None) -> TeXadaConfig:
    """Persist supported user settings to ~/.texada/config.json."""
    target_dir = data_dir or TEXADA_HOME
    config_file = target_dir / "config.json"
    target_dir.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    for key, value in updates.items():
        if key in SAVED_CONFIG_FIELDS:
            existing[key] = value

    tmp_path = config_file.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(config_file)
    try:
        os.chmod(config_file, 0o600)
    except OSError:
        pass
    return TeXadaConfig(data_dir=target_dir, **existing)
