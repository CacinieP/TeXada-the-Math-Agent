"""LlamaServerManager — built-in llama-server sidecar runtime.

Spawns one ``llama-server`` process in router mode (``--models-preset``)
serving both the text and vision models from the configured models
directory. Mirrors the :class:`BackendManager` interface so no call site
branches on runtime identity.

Verified against llama.cpp b11046 (see the runtime design doc, §5.5):
version output ``version: ... (build NNNNN, commit ...)``; mmproj requires
a preset INI; on-demand loading via ``--models-autoload``; idle release via
``--sleep-idle-seconds``; resident-model cap via ``--models-max``.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
from pathlib import Path
from urllib.parse import urlparse

from texada.config import TeXadaConfig
from texada.core.backend import list_models_url, probe_models_url

TEXT_MODEL_FILE = "MiniCPM5-2B-Q4_K_M.gguf"
VISION_MODEL_FILE = "MiniCPM-V-4.6-Q4_K_M.gguf"
VISION_MMPROJ_FILE = "mmproj-MiniCPM-V-4.6-F16.gguf"
VISION_MODEL_FILES = (VISION_MODEL_FILE, VISION_MMPROJ_FILE)

MIN_BUILD = 9049  # MiniCPM-V 4.6 merged into llama.cpp mainline (PR #22529)
STARTUP_TIMEOUT_SECONDS = 60.0
PRESET_NAME = "texada-models.ini"

_BUILD_RE = re.compile(r"build\s+(\d+)")


class LlamaServerError(RuntimeError):
    """Raised when the llama-server runtime cannot be prepared or run."""


class LlamaServerManager:
    """Lifecycle and readiness for the built-in llama-server runtime."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None

    # ── paths and binary resolution ──

    @property
    def models_dir(self) -> Path:
        if self.config.llama_models_dir.strip():
            return Path(self.config.llama_models_dir).expanduser()
        return self.config.data_dir / "models"

    @property
    def text_model_path(self) -> Path:
        return self.models_dir / TEXT_MODEL_FILE

    @property
    def vision_model_paths(self) -> tuple[Path, Path]:
        return (self.models_dir / VISION_MODEL_FILE, self.models_dir / VISION_MMPROJ_FILE)

    def resolve_binary(self) -> Path:
        """Explicit config → packaged location → PATH lookup."""
        explicit = self.config.llama_server_binary.strip()
        if explicit:
            path = Path(explicit).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
            raise LlamaServerError(f"llama-server 二进制不可执行: {path}")

        candidates = [
            # packaged next to the Python sidecar (desktop builds)
            Path(__file__).resolve().parents[2] / "binaries" / "llama-server",
            Path(__file__).resolve().parents[2] / "llama-server",
        ]
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate

        found = shutil.which("llama-server")
        if found:
            return Path(found)
        raise LlamaServerError(
            "未找到 llama-server 二进制。请在设置中指定路径，或安装 llama.cpp "
            "(build >= 9049)。"
        )

    # ── process lifecycle ──

    def _host_port(self) -> tuple[str, int]:
        parsed = urlparse(self.config.llama_server_host)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        return host, port

    def _write_preset(self) -> Path:
        """Generate the router preset INI; mmproj can only be declared here."""
        text = self.text_model_path
        vision, mmproj = self.vision_model_paths
        preset = self.models_dir / PRESET_NAME
        preset.parent.mkdir(parents=True, exist_ok=True)
        preset.write_text(
            "[text]\n"
            f"model = {text}\n"
            "\n"
            "[vision]\n"
            f"model = {vision}\n"
            f"mmproj = {mmproj}\n",
            encoding="utf-8",
        )
        return preset

    def _build_command(self) -> list[str]:
        binary = self.resolve_binary()
        host, port = self._host_port()
        preset = self._write_preset()
        command = [
            str(binary),
            "--models-preset", str(preset),
            "--host", host,
            "--port", str(port),
            "--ctx-size", str(self.config.llama_context_size),
            "--n-gpu-layers", str(self.config.llama_gpu_layers),
            "--models-max", str(self.config.llama_models_max),
        ]
        if self.config.llama_idle_sleep_seconds >= 0:
            command += [
                "--sleep-idle-seconds",
                str(self.config.llama_idle_sleep_seconds),
            ]
        return command

    async def _version_build(self) -> int | None:
        binary = self.resolve_binary()
        try:
            proc = await asyncio.create_subprocess_exec(
                str(binary), "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception:
            return None
        match = _BUILD_RE.search(out.decode("utf-8", errors="replace"))
        return int(match.group(1)) if match else None

    async def _check_version(self) -> None:
        build = await self._version_build()
        if build is not None and build < MIN_BUILD:
            raise LlamaServerError(
                f"llama-server build {build} 过旧，MiniCPM-V 4.6 需要 "
                f"build >= {MIN_BUILD}。"
            )

    async def start(self) -> bool:
        if self._process is not None and self._process.returncode is None:
            return True
        await self._check_version()
        command = self._build_command()
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        base = self.config.active_base_url
        deadline = asyncio.get_event_loop().time() + STARTUP_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            if self._process.returncode is not None:
                exited = self._process
                self._process = None
                raise LlamaServerError(
                    f"llama-server 启动后退出 (exit {exited.returncode})"
                )
            if await probe_models_url(base):
                return True
            await asyncio.sleep(0.5)
        await self.stop()
        raise LlamaServerError(
            f"llama-server 启动超时 ({STARTUP_TIMEOUT_SECONDS:.0f}s)"
        )

    async def stop(self) -> bool:
        proc = self._process
        if proc is None:
            return True
        self._process = None
        if proc.returncode is not None:
            return True
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return True
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            proc.kill()
            await proc.wait()
        return True

    async def ensure_ready(self) -> bool:
        if await probe_models_url(self.config.active_base_url):
            return True
        return await self.start()

    async def ensure_vision_ready(self) -> bool:
        missing = [
            path.name
            for path in self.vision_model_paths
            if not path.is_file()
        ]
        if missing:
            raise LlamaServerError(
                "视觉模型文件缺失: " + ", ".join(missing)
            )
        return await self.ensure_ready()

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    # ── status ──

    def _model_presence(self) -> tuple[bool, bool, bool]:
        """(text, vision model, vision mmproj) file presence."""
        vision, mmproj = self.vision_model_paths
        return self.text_model_path.is_file(), vision.is_file(), mmproj.is_file()

    def _build_status(self, running: bool, installed: list[str] | None = None) -> dict:
        text_present, vision_present, mmproj_present = self._model_presence()
        text_installed = text_present
        vision_installed = vision_present and mmproj_present
        installed = installed or []
        running = running or self.is_running()
        try:
            binary = str(self.resolve_binary())
        except LlamaServerError:
            binary = None

        status = "ready"
        ready = True
        message: str | None = None
        next_action: str | None = None
        if binary is None:
            status, ready = "missing_binary", False
            message = "未找到 llama-server 二进制"
            next_action = "在设置中指定 llama-server 路径"
        elif not running:
            status, ready = "stopped", False
            message = "llama-server 未运行"
            next_action = "点击启动本地推理服务"
        elif not text_installed:
            status, ready = "missing_model", False
            message = "文本模型未下载"
            next_action = "下载 MiniCPM5-2B GGUF"
        elif not vision_installed:
            status, ready = "partial_ready", False
            message = "文本可用，OCR 视觉模型未下载"
            next_action = "下载 MiniCPM-V 4.6 GGUF + mmproj"

        return {
            "status": status,
            "ready": ready,
            "backend": self.config.backend,
            "endpoint": self.config.active_base_url,
            "model": self.config.active_model_name,
            "vision": self.config.active_vision_model_name,
            "message": message,
            "missing_models": [
                name
                for name, present in (
                    (TEXT_MODEL_FILE, text_present),
                    (VISION_MODEL_FILE, vision_present),
                    (VISION_MMPROJ_FILE, mmproj_present),
                )
                if not present
            ],
            "text_model_installed": text_installed,
            "vision_model_installed": vision_installed,
            "binary": binary,
            "models_dir": str(self.models_dir),
            "installed_model_count": len(installed),
            "next_action": next_action,
        }

    def get_status(self) -> dict:
        """Sync status for the UI (no probe)."""
        return self._build_status(self.is_running())

    async def aget_status(self) -> dict:
        """Async status with a live endpoint probe and model listing."""
        running = await probe_models_url(self.config.active_base_url)
        installed = await list_models_url(self.config.active_base_url) if running else []
        return self._build_status(running, installed)
