"""TeXada configuration — Pydantic Settings."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    PydanticBaseSettingsSource,
    JsonConfigSettingsSource,
)


TEXADA_HOME = Path.home() / ".texada"


class TeXadaConfig(BaseSettings):
    """All TeXada settings, loaded from ~/.texada/config.json + env vars.

    TeXada runs fully offline on a local Ollama daemon, loading MiniCPM
    models by tag. Ollama exposes an OpenAI-compatible ``/v1`` endpoint, so
    inference (``texada.core.model``) speaks the standard OpenAI chat API;
    text and vision (OCR) requests hit the same daemon with different tags.
    """

    model_config = SettingsConfigDict(
        json_file=str(TEXADA_HOME / "config.json"),
        json_file_encoding="utf-8",
        env_prefix="TEXADA_",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # ── Ollama backend (MiniCPM) ──
    ollama_host: str = "http://localhost:11434"
    model_name: str = "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"  # Text: MiniCPM5-1B
    vision_model_name: str = "openbmb/minicpm-v4.6:latest"     # Vision: MiniCPM-V 4.6 (OCR)
    temperature: float = 0.1
    max_tokens: int = 2048  # MiniCPM5 is a reasoning model — CoT needs headroom

    # ── Render ──
    default_render_mode: str = "katex"   # "katex" | "latex"
    delimiter: str = "$$"                 # "$$" | "\[" | "$"
    katex_enabled: bool = True
    latex_highlight_enabled: bool = True

    # ── Server ──
    api_host: str = "127.0.0.1"
    api_port: int = 18732

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
