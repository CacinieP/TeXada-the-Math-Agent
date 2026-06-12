"""LlamaCpp Manager — readiness check for llama.cpp servers."""
from __future__ import annotations

import httpx

from texada.config import TeXadaConfig


class LlamaCppManager:
    """Manages llama.cpp server readiness — health check only, no auto-start."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._text_ready = False
        self._vision_ready = False

    async def ensure_ready(self) -> bool:
        """Ensure llama.cpp servers are running."""
        if self._text_ready:
            return True

        # Check text model server
        if not await self._check_health(self.config.llama_host):
            raise RuntimeError(
                f"llama.cpp 文本模型服务未运行 ({self.config.llama_host})。\n"
                f"请先启动: 运行 ~/models/start-minicpm-dual-opencode.ps1"
            )
        self._text_ready = True

        # Check vision model server (for OCR)
        if await self._check_health(self.config.llama_vision_host):
            self._vision_ready = True

        return True

    async def _check_health(self, host: str) -> bool:
        """Check if an OpenAI-compatible server is healthy.

        Uses ``/v1/models`` (the standard OpenAI-compatible readiness endpoint)
        so it works for llama.cpp's server, Ollama's OpenAI shim, and any other
        compatible backend. Falls back to ``/health`` then ``/``.
        """
        for path in ("/v1/models", "/health", "/"):
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{host}{path}")
                    if resp.status_code == 200:
                        return True
            except Exception:
                continue
        return False

    def get_status(self) -> dict:
        """Return current status for the UI."""
        import asyncio
        try:
            text_ok = asyncio.get_event_loop().run_until_complete(
                self._check_health(self.config.llama_host)
            )
        except RuntimeError:
            text_ok = False

        if text_ok:
            return {
                "status": "ready",
                "model": self.config.model_name,
                "vision": self.config.llama_vision_host,
            }
        return {
            "status": "not_running",
            "message": (
                f"llama.cpp 服务未运行。请先启动:\n"
                f"  ~/models/start-minicpm-dual-opencode.ps1"
            ),
        }

    async def aget_status(self) -> dict:
        """Async version of get_status — safe to call from the running event loop
        (e.g. a FastAPI endpoint). The sync get_status uses run_until_complete,
        which raises inside an already-running loop and falsely reports not_running.
        """
        text_ok = await self._check_health(self.config.llama_host)
        if text_ok:
            return {
                "status": "ready",
                "model": self.config.model_name,
                "vision": self.config.llama_vision_host,
            }
        return {
            "status": "not_running",
            "message": (
                f"llama.cpp 服务未运行。请先启动:\n"
                f"  ~/models/start-minicpm-dual-opencode.ps1"
            ),
        }
