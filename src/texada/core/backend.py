"""Backend manager — local Ollama daemon: readiness check + auto-start."""
from __future__ import annotations

import asyncio
import shutil

import httpx

from texada.config import TeXadaConfig


class BackendManager:
    """Manages the local Ollama daemon backing TeXada.

    Ollama exposes an OpenAI-compatible ``/v1`` endpoint; readiness is probed
    via ``/v1/models`` (which also lists pulled models). No ``ollama`` Python
    package is required — checks go through httpx, and the daemon is launched
    via ``ollama serve`` subprocess when it isn't already running.
    """

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._ready = False

    @property
    def base_url(self) -> str:
        return self.config.ollama_host

    async def ensure_ready(self) -> bool:
        """Ensure Ollama is running and the text model is available."""
        if self._ready:
            return True

        # Step 1: daemon running? auto-start once if not.
        if not await self._is_running():
            await self._start_ollama()

        # Step 2: text model pulled? (substring match — tolerant of tag suffixes)
        models = await self._list_models()
        if not any(self.config.model_name in m for m in models):
            raise RuntimeError(
                f"模型 {self.config.model_name} 未安装。请运行: "
                f"ollama pull {self.config.model_name}"
            )

        self._ready = True
        return True

    async def _is_running(self) -> bool:
        """True if the daemon answers on /v1/models."""
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/v1/models")
                return resp.status_code == 200
        except Exception:
            return False

    async def _list_models(self) -> list[str]:
        """List pulled model ids via the OpenAI-compatible endpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/v1/models")
                if resp.status_code != 200:
                    return []
                data = resp.json().get("data", [])
                return [m.get("id", "") for m in data]
        except Exception:
            return []

    async def _start_ollama(self) -> None:
        """Launch ``ollama serve`` if the CLI is available, then wait for readiness."""
        if not shutil.which("ollama"):
            raise RuntimeError(
                "Ollama 未运行且未找到 `ollama` 命令。请安装: https://ollama.com"
            )
        await asyncio.create_subprocess_exec(
            "ollama", "serve",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(30):
            await asyncio.sleep(1)
            if await self._is_running():
                return
        raise RuntimeError("Ollama 启动超时 (30s)")

    def get_status(self) -> dict:
        """Sync status for the UI. Avoid inside a running event loop; prefer
        ``aget_status`` from async code (e.g. FastAPI handlers).
        """
        try:
            running = asyncio.get_event_loop().run_until_complete(self._is_running())
        except RuntimeError:
            running = False
        return self._build_status(running)

    async def aget_status(self) -> dict:
        """Async status — safe to call from within a running event loop."""
        return self._build_status(await self._is_running())

    def _build_status(self, running: bool) -> dict:
        if not running:
            return {"status": "not_running", "message": "Ollama 未运行"}
        return {
            "status": "ready",
            "model": self.config.model_name,
            "vision": self.config.vision_model_name,
        }
