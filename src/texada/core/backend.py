"""Backend manager — readiness checks for local Ollama or OpenAI-compatible APIs."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
from urllib.parse import urlparse

import httpx

from texada.config import TeXadaConfig


async def probe_models_url(
    base_url: str, headers: dict[str, str] | None = None, *, timeout: float = 3.0
) -> bool:
    """True if an OpenAI-compatible API base answers 200 on its /models route.

    Shared by BackendManager (Ollama) and LlamaServerManager so both local
    runtimes prove readiness identically. ``base_url`` is the API base
    (usually ending in /v1), never the complete /models route.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models", headers=headers or {}
            )
            return resp.status_code == 200
    except Exception:
        return False


async def list_models_url(
    base_url: str, headers: dict[str, str] | None = None, *, timeout: float = 5.0
) -> list[str]:
    """List model ids from an API base, appending the /models route once."""
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models", headers=headers or {}
            )
            if resp.status_code != 200:
                return []
            data = resp.json().get("data", [])
            return [m.get("id", "") for m in data]
    except Exception:
        return []


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

        if self.config.uses_llama_server:
            if not await self._is_running():
                raise RuntimeError("llama-server endpoint 不可达，请从运行时设置启动 llama-server")
            models = await self._list_models()
            if not self._model_installed(self.config.active_model_name, models):
                raise RuntimeError(f"llama-server 模型不可用: {self.config.active_model_name}")
            self._ready = True
            return True

        if self.config.uses_openai_compatible:
            self._validate_openai_config()
            if not await self._is_running():
                raise RuntimeError("OpenAI-compatible endpoint 不可达，请检查 endpoint 和 key")
            self._ready = True
            return True

        # Local Ollama: daemon running? auto-start once if this is a local endpoint.
        if not await self._is_running():
            await self._ensure_ollama_running_or_startable()

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
        if self.config.uses_llama_server:
            await self.ensure_ready()
            models = await self._list_models()
            if not self._model_installed(self.config.active_vision_model_name, models):
                raise RuntimeError(
                    f"llama-server 视觉模型不可用: {self.config.active_vision_model_name}"
                )
            return True
        if self.config.uses_openai_compatible:
            self._validate_openai_config(vision=True)
            if not await probe_models_url(self.config.active_vision_base_url, self.vision_headers):
                raise RuntimeError(
                    "OCR OpenAI-compatible endpoint 不可达，请检查 OCR endpoint 和 key"
                )
            return True

        if not await self._is_running():
            await self._ensure_ollama_running_or_startable()

        models = await self._list_models()
        vision_model = self.config.vision_model_name.strip()
        if not vision_model:
            raise RuntimeError("OCR 视觉模型名称未配置")
        if not self._model_installed(vision_model, models):
            raise RuntimeError(
                f"Ollama 模型未安装: {vision_model}。请运行: "
                f"{self._pull_command(vision_model)}"
            )

        self._ready = True
        return True

    @property
    def vision_headers(self) -> dict[str, str]:
        key = self.config.active_vision_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _validate_openai_config(self, *, vision: bool = False) -> None:
        values = (
            (self.config.active_vision_base_url, self.config.active_vision_api_key,
             self.config.active_vision_model_name)
            if vision else (
                self.base_url, self.config.active_api_key, self.config.active_model_name,
            )
        )
        missing = [name for name, value in zip(
            ("endpoint", "api key", "model name"), values, strict=True,
        ) if not value.strip()]
        if missing:
            role = "OCR " if vision else ""
            raise RuntimeError(role + "OpenAI-compatible 配置缺失: " + ", ".join(missing))

    async def _is_running(self) -> bool:
        """True if the backend answers on /models."""
        return await probe_models_url(self.base_url, self.headers)

    async def _list_models(self) -> list[str]:
        """List pulled model ids via the OpenAI-compatible endpoint."""
        return await list_models_url(self.base_url, self.headers)

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

    def _ollama_host_is_local(self) -> bool:
        parsed = urlparse(self.config.ollama_host)
        hostname = parsed.hostname or parsed.path.split(":", 1)[0]
        hostname = hostname.strip("[]").lower()
        if hostname in {"", "localhost"}:
            return True
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return ip.is_loopback or ip.is_unspecified

    async def _ensure_ollama_running_or_startable(self) -> None:
        if not self._ollama_host_is_local():
            raise RuntimeError(
                f"Ollama endpoint 不可达: {self.config.ollama_host}。"
                "请启动远端 Ollama，或检查设置页中的 Ollama 地址和端口。"
            )
        await self._start_ollama()

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
        if self.config.uses_llama_server:
            running = await self._is_running()
            models = await self._list_models() if running else []
            text_ready = running and self._model_installed(self.config.active_model_name, models)
            vision_ready = running and self._model_installed(
                self.config.active_vision_model_name, models
            )
            return {
                "status": "ready"
                if text_ready and vision_ready
                else "partial_ready"
                if text_ready
                else "missing_model"
                if running
                else "not_running",
                "ready": bool(text_ready),
                "backend": self.config.backend,
                "endpoint": self.base_url,
                "model": self.config.active_model_name,
                "vision": self.config.active_vision_model_name,
                "text_model_installed": bool(text_ready),
                "vision_model_installed": bool(vision_ready),
                "missing_models": [
                    m
                    for m in sorted(
                        {self.config.active_model_name, self.config.active_vision_model_name}
                    )
                    if not self._model_installed(m, models)
                ],
                "installed_model_count": len(models),
                "message": None
                if text_ready and vision_ready
                else "请检查 llama-server 运行时与模型配置",
                "next_action": None
                if text_ready and vision_ready
                else "从运行时设置启动 llama-server 或检查模型配置",
            }
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
            text_ready = await self._is_running()
            result = self._build_status(text_ready)
            result["vision_endpoint"] = self.config.active_vision_base_url
            vision_error = None
            try:
                self._validate_openai_config(vision=True)
                same_connection = (
                    self.config.active_vision_base_url == self.base_url
                    and self.vision_headers == self.headers
                )
                vision_ready = text_ready if same_connection else await probe_models_url(
                    self.config.active_vision_base_url, self.vision_headers,
                )
            except RuntimeError as exc:
                vision_ready = False
                vision_error = str(exc)
            result.update(text_model_installed=text_ready, vision_model_installed=vision_ready)
            if text_ready and not vision_ready:
                result.update(status="partial_ready", message=vision_error or "OCR endpoint 不可达")
            return result

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
            local_endpoint = self._ollama_host_is_local()
            return {
                "status": "not_running",
                "ready": False,
                "backend": self.config.backend,
                "endpoint": self.base_url,
                "model": self.config.active_model_name,
                "vision": self.config.active_vision_model_name,
                "message": (
                    "Ollama 未运行" if local_endpoint and cli_available
                    else "Ollama 未安装或未在 PATH 中" if local_endpoint
                    else "Ollama endpoint 不可达"
                ),
                "missing_models": [self.config.model_name, self.config.vision_model_name],
                "ollama_cli_available": cli_available,
                "next_action": (
                    "ollama serve" if local_endpoint and cli_available
                    else "安装 Ollama: https://ollama.com" if local_endpoint
                    else "启动远端 Ollama，或检查 Ollama 地址和端口"
                ),
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
