"""Ollama Manager — lifecycle management: readiness check + auto-start."""
from __future__ import annotations

import asyncio
import sys

import ollama

from texada.config import TeXadaConfig


class OllamaManager:
    """Manages Ollama lifecycle — no 'offline degradation', just service startup."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self.client = ollama.Client(host=config.ollama_host)
        self._ready = False

    async def ensure_ready(self) -> bool:
        """Ensure Ollama is running and model is loaded."""
        if self._ready:
            return True

        # Step 1: Check if Ollama is running
        if not self._is_running():
            await self._start_ollama()

        # Step 2: Check model is available
        models = self.client.list()
        model_names = [m.model for m in models.models] if hasattr(models, 'models') else []
        if not any(self.config.model_name in n for n in model_names):
            raise RuntimeError(
                f"模型 {self.config.model_name} 未安装。请运行: ollama pull {self.config.model_name}"
            )

        self._ready = True
        return True

    def _is_running(self) -> bool:
        try:
            self.client.ps()
            return True
        except Exception:
            return False

    async def _start_ollama(self) -> None:
        """Auto-start Ollama service."""
        proc = await asyncio.create_subprocess_exec(
            "ollama", "serve",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Wait up to 30s for Ollama to be ready
        for _ in range(30):
            await asyncio.sleep(1)
            if self._is_running():
                return
        raise RuntimeError("Ollama 启动超时 (30s)")

    def get_status(self) -> dict:
        """Return current status for the UI."""
        running = self._is_running()
        if not running:
            return {"status": "not_running", "message": "Ollama 未运行"}
        try:
            models = self.client.list()
            model_names = [m.model for m in models.models] if hasattr(models, 'models') else []
            has_model = any(self.config.model_name in n for n in model_names)
            if has_model:
                return {"status": "ready", "model": self.config.model_name}
            return {
                "status": "no_model",
                "message": f"请运行: ollama pull {self.config.model_name}",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}