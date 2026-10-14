"""Owned llama-server lifecycle for the shared MiniCPM-V-4.7-1B checkpoint.

One process serves text and vision under the same alias. Installers contain the
runtime; the checksum-pinned weights and projector are downloaded separately.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import re
import shutil
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from texada.config import TeXadaConfig
from texada.core.backend import list_models_url, probe_models_url

TEXT_MODEL_FILE = "MiniCPM-V-4_7-1B-Q4_K_M.gguf"
VISION_MODEL_FILE = TEXT_MODEL_FILE
VISION_MMPROJ_FILE = "mmproj-model-f16.gguf"
VISION_MODEL_FILES = (VISION_MODEL_FILE, VISION_MMPROJ_FILE)

MIN_BUILD = 11609  # Pinned and locally verified MiniCPM-V 4.7 runtime
STARTUP_TIMEOUT_SECONDS = 60.0
VERSION_TIMEOUT_SECONDS = 15.0
STOP_TIMEOUT_SECONDS = 10.0
KILL_TIMEOUT_SECONDS = 5.0

_BUILD_RE = re.compile(r"build\s+(\d+)")
_IS_WINDOWS = sys.platform == "win32"
_CREATE_SUSPENDED = 0x00000004


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


def _windows_kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    signatures = {
        "CreateJobObjectW": ([handle, ctypes.c_wchar_p], handle),
        "SetInformationJobObject": ([handle, ctypes.c_int, handle, dword], boolean),
        "AssignProcessToJobObject": ([handle, handle], boolean),
        "TerminateJobObject": ([handle, dword], boolean),
        "QueryInformationJobObject": ([handle, ctypes.c_int, handle, dword, handle], boolean),
        "OpenProcess": ([dword, boolean, dword], handle),
        "OpenThread": ([dword, boolean, dword], handle),
        "CreateToolhelp32Snapshot": ([dword, dword], handle),
        "Thread32First": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
        "Thread32Next": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
        "ResumeThread": ([handle], dword),
        "CloseHandle": ([handle], boolean),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def _windows_error(operation: str) -> OSError:
    return OSError(ctypes.get_last_error(), f"Windows {operation} failed")


class _WindowsJob:
    """Non-inheritable job handle for an owned suspended process and its tree.

    Microsoft: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
    No breakaway limits are enabled. The job survives a router's exit and
    KILL_ON_JOB_CLOSE also reclaims workers if the application exits abruptly.
    """

    def __init__(self, api=None):
        self._api = api if api is not None else _windows_kernel32()
        self.assigned = False
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise _windows_error("CreateJobObjectW")
        limits = _JobExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self._api.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = _windows_error("SetInformationJobObject")
            self.close()
            raise error

    def assign_and_resume(self, pid: int) -> None:
        process = self._api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise _windows_error("OpenProcess")
        try:
            if not self._api.AssignProcessToJobObject(self._handle, process):
                raise _windows_error("AssignProcessToJobObject")
            self.assigned = True
        finally:
            self._close_handle(process)

        # subprocess closes CreateProcess's primary thread handle. The process
        # is still suspended, so Toolhelp finds its sole initial thread safely.
        snapshot = self._api.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        if snapshot in (None, 0, ctypes.c_void_p(-1).value):
            raise _windows_error("CreateToolhelp32Snapshot")
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            has_thread = self._api.Thread32First(snapshot, ctypes.byref(entry))
            while has_thread:
                if entry.th32OwnerProcessID == pid:
                    thread = self._api.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise _windows_error("OpenThread")
                    try:
                        suspend_count = self._api.ResumeThread(thread)
                        if suspend_count == 0xFFFFFFFF:
                            raise _windows_error("ResumeThread")
                        if suspend_count != 1:
                            raise OSError("Windows ResumeThread: unexpected suspend count")
                    finally:
                        self._close_handle(thread)
                    return
                entry.dwSize = ctypes.sizeof(entry)
                has_thread = self._api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Windows suspended process has no resumable primary thread")
        finally:
            self._close_handle(snapshot)

    def terminate(self) -> None:
        if not self._api.TerminateJobObject(self._handle, 1):
            raise _windows_error("TerminateJobObject")

    def active_processes(self) -> int:
        accounting = _JobAccountingInformation()
        if not self._api.QueryInformationJobObject(
            self._handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
        ):
            raise _windows_error("QueryInformationJobObject")
        return accounting.ActiveProcesses

    def _close_handle(self, handle) -> None:
        if not self._api.CloseHandle(handle):
            raise _windows_error("CloseHandle")

    def close(self) -> None:
        if self._handle is not None:
            self._close_handle(self._handle)
            self._handle = None


class LlamaServerError(RuntimeError):
    """Raised when the llama-server runtime cannot be prepared or run."""


class LlamaServerManager:
    """Lifecycle and readiness for the built-in llama-server runtime."""

    def __init__(self, config: TeXadaConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._windows_job: _WindowsJob | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._last_error: str | None = None

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
        """Explicit config → shell env var → packaged location → PATH.

        The desktop shell passes TEXADA_LLAMA_SERVER_BINARY pointing at the
        bundled resource; dev checkouts fall back to the tauri resources
        directory, then PATH.
        """
        explicit = self.config.llama_server_binary.strip()
        if explicit:
            path = Path(explicit).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
            raise LlamaServerError(f"llama-server 二进制不可执行: {path}")

        env_path = os.environ.get("TEXADA_LLAMA_SERVER_BINARY", "").strip()
        if env_path:
            path = Path(env_path).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
            raise LlamaServerError(f"TEXADA_LLAMA_SERVER_BINARY 不可执行: {path}")

        here = Path(__file__).resolve()
        executable_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        candidates = [
            # packaged: resources/llama-server/ next to the sidecar executable
            Path(sys.executable).resolve().parent.parent / "llama-server" / executable_name,
            # dev checkout: tauri-shell resources (src layout and installed)
            here.parents[3]
            / "tauri-shell"
            / "src-tauri"
            / "resources"
            / "llama-server"
            / executable_name,
            here.parents[2]
            / "tauri-shell"
            / "src-tauri"
            / "resources"
            / "llama-server"
            / executable_name,
        ]
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate

        for name in ("llama-server", "llama-server.exe"):
            found = shutil.which(name)
            if found:
                return Path(found)
        raise LlamaServerError(
            "未找到 llama-server 二进制。请在设置中指定路径，或安装 llama.cpp (build >= 11609)。"
        )

    # ── process lifecycle ──

    async def _spawn_owned_process(self, command: list[str], *, stdout, stderr):
        if _IS_WINDOWS:
            self._windows_job = _WindowsJob()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=stdout,
                stderr=stderr,
                **(
                    {"creationflags": _CREATE_SUSPENDED}
                    if _IS_WINDOWS
                    else {"start_new_session": True}
                ),
            )
            if self._windows_job is not None:
                self._windows_job.assign_and_resume(self._process.pid)
            return self._process
        except (Exception, asyncio.CancelledError):
            await self._stop_owned_process()
            raise

    async def _terminate_windows_job(self, proc: asyncio.subprocess.Process | None):
        job = self._windows_job
        if job is None:
            return
        deadline = asyncio.get_running_loop().time() + KILL_TIMEOUT_SECONDS
        # Assignment failure leaves a suspended process outside the job. Kill
        # it through asyncio's original handle, never through a recycled PID.
        if not job.assigned and proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        job.terminate()
        while job.active_processes():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise LlamaServerError("Windows llama-server Job 停止超时，worker 仍未退出")
            await asyncio.sleep(min(0.05, remaining))
        if proc is not None and proc.returncode is None:
            try:
                await asyncio.wait_for(
                    proc.wait(), timeout=max(0, deadline - asyncio.get_running_loop().time())
                )
            except TimeoutError as exc:
                raise LlamaServerError("Windows llama-server 父进程停止超时") from exc
        job.close()
        self._windows_job = None

    def _host_port(self) -> tuple[str, int]:
        parsed = urlparse(self.config.llama_server_host)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        return host, port

    def _build_command(self) -> list[str]:
        binary = self.resolve_binary()
        host, port = self._host_port()
        model, mmproj = self.vision_model_paths
        missing = [path.name for path in (model, mmproj) if not path.is_file()]
        if missing:
            raise LlamaServerError("模型文件缺失: " + ", ".join(missing))
        command = [
            str(binary),
            "-m",
            str(model),
            "--mmproj",
            str(mmproj),
            "--alias",
            "MiniCPM-V-4.7-1B",
            "--host",
            host,
            "--port",
            str(port),
            "--ctx-size",
            str(self.config.llama_context_size),
            "--n-gpu-layers",
            str(self.config.llama_gpu_layers),
            "--parallel",
            "1",
            "--jinja",
            "--reasoning",
            "off",
            "--seed",
            "47",
        ]
        if self.config.llama_idle_sleep_seconds >= 0:
            command += ["--sleep-idle-seconds", str(self.config.llama_idle_sleep_seconds)]
        return command

    async def _version_build(self) -> int | None:
        binary = self.resolve_binary()
        proc = None
        try:
            proc = await self._spawn_owned_process(
                [str(binary), "--version"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=VERSION_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise LlamaServerError(
                f"llama-server 版本检查超时 ({VERSION_TIMEOUT_SECONDS:g}s)"
            ) from exc
        except OSError as exc:
            raise LlamaServerError(f"llama-server 版本检查失败: {exc}") from exc
        finally:
            if proc is not None:
                await self._terminate_owned_process(proc)
                if self._process is proc:
                    self._process = None
        match = _BUILD_RE.search(out.decode("utf-8", errors="replace"))
        return int(match.group(1)) if match else None

    async def _check_version(self) -> None:
        build = await self._version_build()
        if build is not None and build < MIN_BUILD:
            raise LlamaServerError(
                f"llama-server build {build} 过旧，MiniCPM-V 4.7 需要 build >= {MIN_BUILD}。"
            )

    async def start(self) -> bool:
        async with self._lifecycle_lock:
            if self.is_running():
                return True
            await self._stop_owned_process()
            self._last_error = None
            # A reachable service was not spawned by us. Attach without taking
            # ownership, so stop/settings/shutdown cannot terminate it.
            if await probe_models_url(self.config.active_base_url):
                return True
            try:
                await self._check_version()
                command = self._build_command()
                await self._spawn_owned_process(
                    command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                base = self.config.active_base_url
                deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_SECONDS
                while asyncio.get_running_loop().time() < deadline:
                    if self._process.returncode is not None:
                        raise LlamaServerError(
                            f"llama-server 启动后退出 (exit {self._process.returncode})"
                        )
                    if await probe_models_url(base):
                        return True
                    await asyncio.sleep(0.5)
                raise LlamaServerError(f"llama-server 启动超时 ({STARTUP_TIMEOUT_SECONDS:.0f}s)")
            except (Exception, asyncio.CancelledError) as exc:
                await self._stop_owned_process()
                if isinstance(exc, asyncio.CancelledError):
                    self._last_error = "llama-server 启动被取消"
                    raise
                self._last_error = f"llama-server 启动失败: {exc}"
                if isinstance(exc, LlamaServerError):
                    raise
                raise LlamaServerError(self._last_error) from exc

    @staticmethod
    def _signal_owned_process(proc: asyncio.subprocess.Process, *, kill: bool) -> None:
        if _IS_WINDOWS:
            proc.kill() if kill else proc.terminate()
        else:
            # Every owned process starts in a new session. Only that session's
            # process group is signalled, including router child processes.
            os.killpg(proc.pid, signal.SIGKILL if kill else signal.SIGTERM)

    @staticmethod
    async def _kill_remaining_owned_group(proc: asyncio.subprocess.Process) -> None:
        if not _IS_WINDOWS:
            deadline = asyncio.get_running_loop().time() + min(0.25, KILL_TIMEOUT_SECONDS)
            while True:
                try:
                    # A router child can ignore SIGTERM when its parent exits.
                    os.killpg(proc.pid, signal.SIGKILL)
                    return
                except ProcessLookupError:
                    return
                except PermissionError:
                    # macOS can return EPERM while an empty group is being
                    # removed. Retry briefly; persistent errors remain visible.
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(0.01)

    async def _terminate_owned_process(self, proc: asyncio.subprocess.Process) -> None:
        if self._windows_job is not None:
            await self._terminate_windows_job(proc)
            return
        if proc.returncode is not None:
            await self._kill_remaining_owned_group(proc)
            return
        try:
            self._signal_owned_process(proc, kill=False)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=STOP_TIMEOUT_SECONDS)
            await self._kill_remaining_owned_group(proc)
            return
        except TimeoutError:
            pass
        try:
            self._signal_owned_process(proc, kill=True)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=KILL_TIMEOUT_SECONDS)
            await self._kill_remaining_owned_group(proc)
        except TimeoutError as exc:
            raise LlamaServerError("llama-server 停止失败：SIGTERM 和强制结束后仍未退出") from exc

    async def _stop_owned_process(self) -> None:
        proc = self._process
        if proc is None and self._windows_job is None:
            return
        try:
            if proc is None:
                await self._terminate_windows_job(None)
            else:
                await self._terminate_owned_process(proc)
        except (LlamaServerError, OSError) as exc:
            self._last_error = f"llama-server 停止失败: {exc}"
            # Keep the handle so a failed stop cannot silently orphan it.
            raise LlamaServerError(self._last_error) from exc
        self._process = None

    async def stop(self) -> bool:
        async with self._lifecycle_lock:
            await self._stop_owned_process()
            self._last_error = None
            return True

    async def ensure_ready(self) -> bool:
        if await probe_models_url(self.config.active_base_url):
            return True
        return await self.start()

    async def ensure_vision_ready(self) -> bool:
        missing = [path.name for path in self.vision_model_paths if not path.is_file()]
        if missing:
            raise LlamaServerError("视觉模型文件缺失: " + ", ".join(missing))
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
            next_action = "下载 MiniCPM-V 4.7 GGUF + mmproj"

        if self._last_error:
            status, ready = "error", False
            message = self._last_error
            next_action = "检查本地服务状态后重试启动或停止"

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
            "process_owned": self._process is not None or self._windows_job is not None,
            "last_error": self._last_error,
        }

    def get_status(self) -> dict:
        """Sync status for the UI (no probe)."""
        return self._build_status(self.is_running())

    async def aget_status(self) -> dict:
        """Async status with a live endpoint probe and model listing."""
        running = await probe_models_url(self.config.active_base_url)
        installed = await list_models_url(self.config.active_base_url) if running else []
        return self._build_status(running, installed)
