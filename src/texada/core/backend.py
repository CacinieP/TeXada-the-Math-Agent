"""Backend manager — readiness checks for local Ollama or OpenAI-compatible APIs."""
from __future__ import annotations

import asyncio
import os
import shutil
from urllib.parse import urlparse

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
        return self.config.active_base_url

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/models"

    @property
    def headers(self) -> dict[str, str]:
        if self.config.uses_openai_compatible and self.config.openai_api_key:
            return {"Authorization": f"Bearer {self.config.openai_api_key}"}
        return {}

    async def ensure_ready(self) -> bool:
        """Ensure the configured inference backend is reachable."""
        if self._ready:
            return True

        if self.config.uses_openai_compatible:
            self._validate_openai_config()
            if not await self._is_running():
                raise RuntimeError("OpenAI-compatible endpoint 不可达，请检查 endpoint 和 key")
            self._ready = True
            return True

        # Local Ollama: daemon running? auto-start once if not.
        if not await self._is_running():
            await self._start_ollama()

        models = await self._list_models()
        if not any(self.config.model_name in m for m in models):
            raise RuntimeError(
                f"模型 {self.config.model_name} 未安装。请运行: "
                f"ollama pull {self.config.model_name}"
            )

        self._ready = True
        return True

    async def ensure_vision_ready(self) -> bool:
        """Ensure the configured backend and vision model are reachable."""
        if self.config.uses_openai_compatible:
            return await self.ensure_ready()

        if not await self._is_running():
            await self._start_ollama()

        models = await self._list_models()
        missing = self._missing_local_models(models, include_vision=True)
        if missing:
            commands = " && ".join(self._pull_command(model) for model in missing)
            raise RuntimeError(f"Ollama 模型未安装: {', '.join(missing)}。请运行: {commands}")

        self._ready = True
        return True

    def _validate_openai_config(self) -> None:
        missing: list[str] = []
        if not self.config.openai_base_url.strip():
            missing.append("endpoint")
        if not self.config.openai_api_key.strip():
            missing.append("api key")
        if not self.config.openai_model_name.strip():
            missing.append("model name")
        if missing:
            raise RuntimeError("OpenAI-compatible 配置缺失: " + ", ".join(missing))

    async def _is_running(self) -> bool:
        """True if the backend answers on /models."""
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                resp = await client.get(self.models_url, headers=self.headers)
                return resp.status_code == 200
        except Exception:
            return False

    async def _list_models(self) -> list[str]:
        """List pulled model ids via the OpenAI-compatible endpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(self.models_url, headers=self.headers)
                if resp.status_code != 200:
                    return []
                data = resp.json().get("data", [])
                return [m.get("id", "") for m in data]
        except Exception:
            return []

    def _model_installed(self, model: str, installed_models: list[str]) -> bool:
        model = model.strip()
        if not model:
            return True
        return any(model == item or model in item for item in installed_models)

    def _missing_local_models(
        self,
        installed_models: list[str],
        *,
        include_vision: bool,
    ) -> list[str]:
        missing: list[str] = []
        if not self._model_installed(self.config.model_name, installed_models):
            missing.append(self.config.model_name)
        vision_model = self.config.vision_model_name
        if (
            include_vision
            and vision_model
            and vision_model != self.config.model_name
            and not self._model_installed(vision_model, installed_models)
        ):
            missing.append(vision_model)
        return missing

    def _pull_command(self, model: str) -> str:
        return f"ollama pull {model}"

    def _ollama_server_env(self) -> dict[str, str]:
        env = os.environ.copy()
        parsed = urlparse(self.config.ollama_host)
        host = parsed.netloc or parsed.path
        if host:
            env["OLLAMA_HOST"] = host
        return env

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
            env=self._ollama_server_env(),
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
        if self.config.uses_openai_compatible:
            try:
                self._validate_openai_config()
            except RuntimeError as e:
                return {
                    "status": "not_configured",
                    "ready": False,
                    "backend": self.config.backend,
                    "endpoint": self.base_url,
                    "model": self.config.active_model_name or None,
                    "vision": self.config.active_vision_model_name or None,
                    "message": str(e),
                    "missing_models": [],
                }
            return self._build_status(await self._is_running())

        running = await self._is_running()
        if not running:
            return self._build_status(False)

        models = await self._list_models()
        text_installed = self._model_installed(self.config.model_name, models)
        vision_installed = self._model_installed(self.config.vision_model_name, models)
        missing = self._missing_local_models(models, include_vision=True)

        status = "ready"
        ready = True
        message: str | None = None
        next_action: str | None = None
        if not text_installed:
            status = "missing_model"
            ready = False
            message = "文本模型未安装"
            next_action = self._pull_command(self.config.model_name)
        elif not vision_installed:
            status = "partial_ready"
            message = "文本可用，OCR 视觉模型未安装"
            next_action = self._pull_command(self.config.vision_model_name)

        return {
            "status": status,
            "ready": ready,
            "backend": self.config.backend,
            "endpoint": self.base_url,
            "model": self.config.active_model_name,
            "vision": self.config.active_vision_model_name,
            "message": message,
            "missing_models": missing,
            "text_model_installed": text_installed,
            "vision_model_installed": vision_installed,
            "installed_model_count": len(models),
            "ollama_cli_available": bool(shutil.which("ollama")),
            "next_action": next_action,
        }

    def _build_status(self, running: bool) -> dict:
        if not running:
            if self.config.uses_openai_compatible:
                return {
                    "status": "not_running",
                    "ready": False,
                    "backend": self.config.backend,
                    "endpoint": self.base_url,
                    "model": self.config.active_model_name or None,
                    "vision": self.config.active_vision_model_name or None,
                    "message": "OpenAI-compatible endpoint 不可达",
                    "missing_models": [],
                }
            cli_available = bool(shutil.which("ollama"))
            return {
                "status": "not_running",
                "ready": False,
                "backend": self.config.backend,
                "endpoint": self.base_url,
                "model": self.config.active_model_name,
                "vision": self.config.active_vision_model_name,
                "message": "Ollama 未运行" if cli_available else "Ollama 未安装或未在 PATH 中",
                "missing_models": [self.config.model_name, self.config.vision_model_name],
                "ollama_cli_available": cli_available,
                "next_action": "ollama serve" if cli_available else "安装 Ollama: https://ollama.com",
            }
        return {
            "status": "ready",
            "ready": True,
            "backend": self.config.backend,
            "endpoint": self.base_url,
            "model": self.config.active_model_name,
            "vision": self.config.active_vision_model_name,
            "message": None,
            "missing_models": [],
        }
