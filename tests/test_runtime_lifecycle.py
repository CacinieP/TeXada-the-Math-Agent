"""Owned subprocess cleanup and external-service boundaries, without models."""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import socket
import sys
import textwrap
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi.testclient import TestClient

import texada.core.llama_server as llama_server
from texada.api import create_app
from texada.config import TeXadaConfig, save_config_updates
from texada.core.backend import probe_models_url
from texada.core.llama_server import LlamaServerError, LlamaServerManager

FAKE_SERVER = textwrap.dedent("""\
    import json, signal, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    if '--version' in sys.argv:
        print('version: fake (build 11046, commit deadbeef)')
        sys.exit(0)
    port = int(sys.argv[sys.argv.index('--port') + 1])
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'data': [{'id': 'text'}, {'id': 'vision'}]}).encode()
            self.send_response(200 if self.path == '/v1/models' else 404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
""")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def runtime_config(tmp_path):
    binary = tmp_path / "fake-llama-server"
    binary.write_text(f"#!{sys.executable}\n" + FAKE_SERVER, encoding="utf-8")
    binary.chmod(0o755)
    return save_config_updates({
        "backend": "llama_server",
        "llama_server_binary": str(binary),
        "llama_server_host": f"http://127.0.0.1:{free_port()}",
    }, data_dir=tmp_path)


@pytest.fixture
def external_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"data": []}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def test_start_and_stop_never_take_ownership_of_external_service(
    tmp_path, external_server, monkeypatch
):
    manager = LlamaServerManager(TeXadaConfig(
        data_dir=tmp_path, llama_server_host=external_server
    ))

    async def must_not_spawn(*args, **kwargs):
        pytest.fail("A reachable external endpoint must not spawn a process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", must_not_spawn)
    assert await manager.start() is True
    assert manager._process is None
    assert await manager.stop() is True
    assert await probe_models_url(manager.config.active_base_url) is True


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/settings/backend", {"llama_context_size": 8192}),
    ("/api/import", {"settings": {"backend": "ollama"}}),
])
async def test_api_reconfiguration_reaps_owned_process_before_replacement(
    runtime_config, monkeypatch, endpoint, payload
):
    managers = []

    def tracking_manager(config):
        manager = LlamaServerManager(config)
        managers.append(manager)
        return manager

    monkeypatch.setattr("texada.api.LlamaServerManager", tracking_manager)
    with TestClient(create_app(runtime_config)) as client:
        assert client.post("/api/llama/start").status_code == 200
        old_manager = managers[0]
        owned_process = old_manager._process
        assert owned_process is not None and owned_process.returncode is None
        assert client.post(endpoint, json=payload).status_code == 200
        assert len(managers) == 2
        assert owned_process.returncode is not None
        assert old_manager._process is None
        assert await probe_models_url(runtime_config.active_base_url) is False


async def test_app_shutdown_reaps_owned_process(runtime_config, monkeypatch):
    managers = []

    def tracking_manager(config):
        manager = LlamaServerManager(config)
        managers.append(manager)
        return manager

    monkeypatch.setattr("texada.api.LlamaServerManager", tracking_manager)
    with TestClient(create_app(runtime_config)) as client:
        assert client.post("/api/llama/start").status_code == 200
        proc = managers[0]._process
        assert proc is not None and proc.returncode is None
    assert proc.returncode is not None
    assert managers[0]._process is None
    assert await probe_models_url(runtime_config.active_base_url) is False


async def test_api_settings_backup_and_shutdown_preserve_external_service(
    tmp_path, external_server
):
    config = save_config_updates({
        "backend": "llama_server", "llama_server_host": external_server
    }, data_dir=tmp_path)
    with TestClient(create_app(config)) as client:
        assert client.post("/api/llama/start").status_code == 200
        assert client.post(
            "/api/settings/backend", json={"llama_context_size": 8192}
        ).status_code == 200
        assert client.post(
            "/api/import", json={"settings": {"ui_language": "en"}}
        ).status_code == 200
    assert await probe_models_url(config.active_base_url) is True


async def test_shutdown_stops_current_manager(tmp_path, monkeypatch):
    calls = []

    class Manager:
        async def stop(self):
            calls.append("stop")
            return True

    monkeypatch.setattr("texada.api.LlamaServerManager", lambda config: Manager())
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path))):
        assert calls == []
    assert calls == ["stop"]


async def test_stop_escalates_to_kill_with_bounded_wait(runtime_config, monkeypatch):
    binary = runtime_config.llama_server_binary
    with open(binary, encoding="utf-8") as stream:
        script = stream.read()
    with open(binary, "w", encoding="utf-8") as stream:
        stream.write(script.replace(
            "port = int", "signal.signal(signal.SIGTERM, signal.SIG_IGN)\nport = int"
        ))
    monkeypatch.setattr("texada.core.llama_server.STOP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("texada.core.llama_server.KILL_TIMEOUT_SECONDS", 0.5)
    manager = LlamaServerManager(runtime_config)
    await manager.start()
    proc = manager._process
    try:
        assert await asyncio.wait_for(manager.stop(), timeout=1) is True
        assert proc.returncode is not None and proc.returncode != 0
        assert manager._process is None
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


@pytest.mark.skipif(os.name == "nt", reason="Unix session process-group ownership")
async def test_stop_reaps_parent_and_terminates_term_ignoring_child(runtime_config):
    binary = runtime_config.llama_server_binary
    with open(binary, encoding="utf-8") as stream:
        script = stream.read()
    fork = (
        "import os, time\n"
        "if os.fork():\n"
        "    while True: time.sleep(1)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "port = int"
    )
    with open(binary, "w", encoding="utf-8") as stream:
        stream.write(script.replace("port = int", fork))
    manager = LlamaServerManager(runtime_config)
    await manager.start()
    proc = manager._process
    try:
        assert await manager.stop() is True
        assert proc.returncode is not None
        assert manager._process is None
        async with asyncio.timeout(1):
            while await probe_models_url(runtime_config.active_base_url):
                await asyncio.sleep(0.01)
    finally:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass
        if proc.returncode is None:
            await proc.wait()


async def test_failed_stop_retains_owned_handle_and_diagnostic(tmp_path, monkeypatch):
    class StuckProcess:
        returncode = None

        async def wait(self):
            await asyncio.Event().wait()

    signals = []
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    manager._process = StuckProcess()
    monkeypatch.setattr(
        manager, "_signal_owned_process", lambda proc, *, kill: signals.append(kill)
    )
    monkeypatch.setattr("texada.core.llama_server.STOP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("texada.core.llama_server.KILL_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(LlamaServerError, match="停止失败"):
        await asyncio.wait_for(manager.stop(), timeout=1)
    assert signals == [False, True]
    assert manager._process is not None
    status = manager.get_status()
    assert status["status"] == "error"
    assert status["process_owned"] is True
    assert "停止失败" in status["last_error"]


async def test_version_timeout_reaps_version_subprocess(runtime_config, monkeypatch):
    binary = runtime_config.llama_server_binary
    with open(binary, encoding="utf-8") as stream:
        script = stream.read()
    with open(binary, "w", encoding="utf-8") as stream:
        stream.write(script.replace(
            "print('version", "import time; time.sleep(30)\n    print('version"
        ))
    processes = []
    create_process = asyncio.create_subprocess_exec

    async def capture_process(*args, **kwargs):
        proc = await create_process(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_process)
    monkeypatch.setattr("texada.core.llama_server.VERSION_TIMEOUT_SECONDS", 0.05)
    manager = LlamaServerManager(runtime_config)
    with pytest.raises(LlamaServerError, match="版本检查超时"):
        await manager.start()
    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert manager._process is None
    assert manager.get_status()["status"] == "error"


async def test_start_cancellation_reaps_spawned_process(runtime_config, monkeypatch):
    async def unavailable(*args, **kwargs):
        return False

    monkeypatch.setattr("texada.core.llama_server.probe_models_url", unavailable)
    server_spawned = asyncio.Event()
    server_processes = []
    create_process = asyncio.create_subprocess_exec

    async def capture_process(*args, **kwargs):
        proc = await create_process(*args, **kwargs)
        if "--version" not in args:
            server_processes.append(proc)
            server_spawned.set()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_process)
    manager = LlamaServerManager(runtime_config)
    task = asyncio.create_task(manager.start())
    try:
        await asyncio.wait_for(server_spawned.wait(), timeout=2)
        proc = server_processes[0]
        assert manager._process is proc
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert proc.returncode is not None
        assert manager._process is None
    finally:
        task.cancel()
        await manager.stop()


async def test_stop_failure_blocks_settings_and_backup_mutations(tmp_path, monkeypatch):
    class FailedManager:
        fail = True

        async def stop(self):
            if self.fail:
                raise LlamaServerError("owned process did not exit")
            return True

    manager = FailedManager()
    monkeypatch.setattr("texada.api.LlamaServerManager", lambda config: manager)
    config = save_config_updates({"backend": "llama_server"}, data_dir=tmp_path)
    with TestClient(create_app(config)) as client:
        try:
            response = client.post("/api/settings/backend", json={"backend": "ollama"})
            assert response.status_code == 503
            response = client.post("/api/import", json={
                "settings": {"backend": "ollama"}, "shorthands": {"new": "x^2"}
            })
            assert response.status_code == 503
            assert "owned process" in response.json()["detail"]
            assert json.loads((tmp_path / "config.json").read_text())["backend"] == "llama_server"
            assert "new" not in {item["key"] for item in client.get("/api/shorthands").json()}
        finally:
            manager.fail = False


async def test_settings_transition_serializes_concurrent_start(tmp_path, monkeypatch):
    stop_started = asyncio.Event()
    allow_stop = asyncio.Event()
    managers = []

    class Manager:
        def __init__(self, config):
            self.started = False
            managers.append(self)

        async def stop(self):
            if self is managers[0]:
                stop_started.set()
                await allow_stop.wait()

        async def start(self):
            self.started = True

        async def aget_status(self):
            return {"status": "ready", "ready": True}

    monkeypatch.setattr("texada.api.LlamaServerManager", Manager)
    config = save_config_updates({"backend": "llama_server"}, data_dir=tmp_path)
    app = create_app(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        update = asyncio.create_task(c.post(
            "/api/settings/backend", json={"llama_context_size": 8192}
        ))
        await asyncio.wait_for(stop_started.wait(), timeout=1)
        start = asyncio.create_task(c.post("/api/llama/start"))
        await asyncio.sleep(0)
        allow_stop.set()
        assert (await update).status_code == 200
        assert (await start).status_code == 200
    assert len(managers) == 2
    assert managers[0].started is False
    assert managers[1].started is True


class WindowsFunction:
    def __init__(self, api, name, implementation):
        self.api, self.name, self.implementation = api, name, implementation
        self.argtypes = self.restype = None

    def __call__(self, *args):
        self.api.calls.append((self.name, args))
        if self.name in self.api.fail:
            return 0xFFFFFFFF if self.name == "ResumeThread" else 0
        return self.implementation(*args)


class WindowsParent:
    pid = 4000
    returncode = None
    killed = False

    def kill(self):
        self.killed, self.returncode = True, 1

    async def wait(self):
        return self.returncode


class WindowsKernel:
    """API contract model; real Win32 behavior is covered by Windows-only tests."""
    job_handle, process_handle = 0x100000001, 0x100000002
    snapshot_handle, thread_handle = 0x100000003, 0x100000004

    def __init__(self):
        self.calls, self.closed, self.fail = [], [], set()
        self.parent = WindowsParent()
        self.worker_running = False
        self.external_worker_running = True
        self.active, self.stuck = 0, False
        for name in (
            "CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject",
            "TerminateJobObject", "QueryInformationJobObject", "OpenProcess", "OpenThread",
            "CreateToolhelp32Snapshot", "Thread32First", "Thread32Next", "ResumeThread",
            "CloseHandle",
        ):
            setattr(self, name, WindowsFunction(self, name, getattr(self, "_" + name)))

    def _CreateJobObjectW(self, security, name):
        assert security is None and name is None  # unnamed and non-inheritable
        return self.job_handle

    def _SetInformationJobObject(self, handle, kind, pointer, size):
        limits = ctypes.cast(
            pointer, ctypes.POINTER(llama_server._JobExtendedLimitInformation)
        ).contents
        assert handle == self.job_handle and kind == 9
        assert size == ctypes.sizeof(limits)
        assert limits.BasicLimitInformation.LimitFlags == 0x2000
        return 1

    def _OpenProcess(self, rights, inherit, pid):
        assert rights == 0x0101 and not inherit and pid == self.parent.pid
        return self.process_handle

    def _AssignProcessToJobObject(self, job, process):
        assert job == self.job_handle and process == self.process_handle
        self.active = 1
        return 1

    def _CreateToolhelp32Snapshot(self, flags, pid):
        assert flags == 4 and pid == 0
        return self.snapshot_handle

    def _Thread32First(self, snapshot, pointer):
        entry = ctypes.cast(pointer, ctypes.POINTER(llama_server._ThreadEntry)).contents
        assert snapshot == self.snapshot_handle and entry.dwSize == 28
        entry.th32OwnerProcessID, entry.th32ThreadID = 999, 11
        return 1

    def _Thread32Next(self, snapshot, pointer):
        entry = ctypes.cast(pointer, ctypes.POINTER(llama_server._ThreadEntry)).contents
        entry.th32OwnerProcessID, entry.th32ThreadID = self.parent.pid, 12
        return 1

    def _OpenThread(self, rights, inherit, tid):
        assert rights == 2 and not inherit and tid == 12
        return self.thread_handle

    def _ResumeThread(self, handle):
        assert handle == self.thread_handle and self.active == 1
        self.active, self.worker_running = 2, True
        return 1

    def _TerminateJobObject(self, handle, code):
        assert handle == self.job_handle and code == 1
        if not self.stuck:
            self.active, self.worker_running = 0, False
            self.parent.returncode = 1
        return 1

    def _QueryInformationJobObject(self, handle, kind, pointer, size, returned):
        accounting = ctypes.cast(
            pointer, ctypes.POINTER(llama_server._JobAccountingInformation)
        ).contents
        assert handle == self.job_handle and kind == 1
        assert size == 48 and returned is None
        accounting.ActiveProcesses = self.active
        return 1

    def _CloseHandle(self, handle):
        assert handle not in self.closed
        self.closed.append(handle)
        return 1


@pytest.fixture
def windows_kernel(monkeypatch):
    api = WindowsKernel()
    monkeypatch.setattr(llama_server, "_IS_WINDOWS", True)
    monkeypatch.setattr(llama_server, "_windows_kernel32", lambda: api)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    return api


async def test_windows_job_fixed_width_layout_and_pointer_handle_signatures(monkeypatch):
    api = WindowsKernel()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False)
    assert llama_server._windows_kernel32() is api
    assert api.CreateJobObjectW.restype is ctypes.c_void_p
    assert api.OpenProcess.restype is ctypes.c_void_p
    assert api.OpenThread.restype is ctypes.c_void_p
    assert api.CreateToolhelp32Snapshot.restype is ctypes.c_void_p
    assert api.CloseHandle.argtypes == [ctypes.c_void_p]
    assert api.AssignProcessToJobObject.argtypes == [ctypes.c_void_p, ctypes.c_void_p]
    assert api.ResumeThread.restype is ctypes.c_uint32
    assert ctypes.sizeof(llama_server._ThreadEntry) == 28
    assert ctypes.sizeof(llama_server._JobAccountingInformation) == 48
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(llama_server._JobBasicLimitInformation) == 64
        assert ctypes.sizeof(llama_server._JobExtendedLimitInformation) == 144


async def test_windows_job_assigns_suspended_process_before_resume(
    tmp_path, windows_kernel, monkeypatch
):
    api = windows_kernel

    async def spawn(*command, **options):
        assert options["creationflags"] == 4
        assert "start_new_session" not in options
        assert api.calls[1][0] == "SetInformationJobObject"
        assert not api.worker_running
        api.calls.append(("spawn_suspended", command))
        return api.parent

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    assert await manager._spawn_owned_process(["fake"], stdout=None, stderr=None) is api.parent
    names = [name for name, args in api.calls]
    assert names.index("spawn_suspended") < names.index("AssignProcessToJobObject")
    assert names.index("AssignProcessToJobObject") < names.index("ResumeThread")
    assert api.closed == [api.process_handle, api.thread_handle, api.snapshot_handle]
    assert api.worker_running
    await manager.stop()
    assert manager._process is None and manager._windows_job is None
    assert not api.worker_running and api.external_worker_running
    assert api.closed[-1] == api.job_handle


@pytest.mark.parametrize("failure", ["AssignProcessToJobObject", "ResumeThread"])
async def test_windows_job_assignment_or_resume_failure_reclaims_suspended_process(
    tmp_path, windows_kernel, monkeypatch, failure
):
    api = windows_kernel
    api.fail.add(failure)

    async def spawn(*args, **kwargs):
        return api.parent

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    with pytest.raises(OSError, match=failure):
        await manager._spawn_owned_process(["fake"], stdout=None, stderr=None)
    assert api.parent.returncode is not None
    if failure == "AssignProcessToJobObject":
        assert api.parent.killed
        assert not any(name == "ResumeThread" for name, args in api.calls)
    assert manager._process is None and manager._windows_job is None
    assert api.job_handle in api.closed


async def test_windows_job_spawn_failure_closes_empty_job(tmp_path, windows_kernel, monkeypatch):
    async def spawn(*args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    with pytest.raises(OSError, match="spawn failed"):
        await manager._spawn_owned_process(["fake"], stdout=None, stderr=None)
    assert manager._process is None and manager._windows_job is None
    assert windows_kernel.closed == [windows_kernel.job_handle]


@pytest.mark.parametrize("failure", ["TerminateJobObject", "QueryInformationJobObject", "stuck"])
async def test_windows_job_stop_failure_preserves_job_after_parent_exit(
    tmp_path, windows_kernel, monkeypatch, failure
):
    api = windows_kernel
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    job = llama_server._WindowsJob()
    job.assign_and_resume(api.parent.pid)
    api.parent.returncode, api.active = 0, 1
    manager._process, manager._windows_job = api.parent, job
    if failure == "stuck":
        api.stuck = True
    else:
        api.fail.add(failure)
    monkeypatch.setattr(llama_server, "KILL_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(LlamaServerError, match="停止失败"):
        await asyncio.wait_for(manager.stop(), timeout=1)
    assert manager._windows_job is job and manager._process is api.parent
    assert api.job_handle not in api.closed
    assert manager.get_status()["process_owned"] is True
    api.fail.clear()
    api.stuck = False
    await manager.stop()
    assert manager._windows_job is None and manager._process is None


@pytest.mark.parametrize("transition", ["settings", "import", "shutdown"])
async def test_windows_job_api_cleanup_preserves_external_worker_after_parent_exit(
    tmp_path, windows_kernel, monkeypatch, transition
):
    api = windows_kernel
    managers = []

    def factory(config):
        manager = LlamaServerManager(config)
        if not managers:
            job = llama_server._WindowsJob()
            job.assign_and_resume(api.parent.pid)
            api.parent.returncode, api.active = 0, 1
            manager._process, manager._windows_job = api.parent, job
        managers.append(manager)
        return manager

    monkeypatch.setattr("texada.api.LlamaServerManager", factory)
    config = save_config_updates({"backend": "llama_server"}, data_dir=tmp_path)
    with TestClient(create_app(config)) as client:
        if transition == "settings":
            assert client.post(
                "/api/settings/backend", json={"backend": "ollama"}
            ).status_code == 200
        elif transition == "import":
            assert client.post(
                "/api/import", json={"settings": {"backend": "ollama"}}
            ).status_code == 200
    assert managers[0]._windows_job is None and managers[0]._process is None
    assert not api.worker_running and api.external_worker_running


WINDOWS_ROUTER = textwrap.dedent("""\
    import json, subprocess, sys, time
    from pathlib import Path
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port, pid_file, exit_file = sys.argv[1:4]
    if len(sys.argv) > 4:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'data': [{'id': 'text'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        HTTPServer(('127.0.0.1', int(port)), Handler).serve_forever()
    else:
        worker = subprocess.Popen([sys.executable, __file__, port, pid_file, exit_file, 'worker'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path(pid_file).write_text(str(worker.pid))
        while not Path(exit_file).exists(): time.sleep(0.01)
""")


@pytest.fixture
def windows_real_tree(tmp_path):
    script, pid_file, exit_file = (
        tmp_path / "router.py", tmp_path / "worker.pid", tmp_path / "parent.exit"
    )
    script.write_text(WINDOWS_ROUTER, encoding="utf-8")
    port = free_port()

    class TreeManager(LlamaServerManager):
        def _build_command(self):
            return [sys.executable, str(script), str(port), str(pid_file), str(exit_file)]

    config = save_config_updates({
        "backend": "llama_server", "llama_server_binary": sys.executable,
        "llama_server_host": f"http://127.0.0.1:{port}",
    }, data_dir=tmp_path)
    return config, TreeManager, pid_file, exit_file


def windows_worker_handle(pid_file):
    api = llama_server._windows_kernel32()
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    handle = api.OpenProcess(0x00100000, False, int(pid_file.read_text()))  # SYNCHRONIZE
    assert handle
    return api, handle


@pytest.mark.skipif(os.name != "nt", reason="Requires real Windows kernel Job Objects")
@pytest.mark.parametrize("parent_exits", [False, True])
async def test_windows_job_terminates_real_tree_with_live_or_exited_parent(
    windows_real_tree, parent_exits, monkeypatch
):
    config, TreeManager, pid_file, exit_file = windows_real_tree
    manager = TreeManager(config)
    api = handle = None
    original_close = None
    try:
        assert await manager.start()
        api, handle = windows_worker_handle(pid_file)
        job = manager._windows_job
        assert job is not None
        active_at_close = []
        original_close = job.close

        def record_close():
            active_at_close.append(job.active_processes())
            original_close()

        monkeypatch.setattr(job, "close", record_close)
        if parent_exits:
            exit_file.touch()
            await asyncio.wait_for(manager._process.wait(), timeout=3)
            assert manager._process.returncode == 0
            assert await probe_models_url(config.active_base_url)
            assert api.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: worker still alive
            # Job accounting counts OS processes, including interpreter
            # launchers; a logical worker need not occupy exactly one member.
            assert job.active_processes() >= 1
        await manager.stop()
        assert api.WaitForSingleObject(handle, 5000) == 0  # worker identity, not parent PID
        assert active_at_close == [0]  # every job member exited before handle release
        assert manager._windows_job is None and manager._process is None
        assert not await probe_models_url(config.active_base_url)
    finally:
        if handle is not None:
            api.CloseHandle(handle)
        if manager._windows_job is not None:
            # Bypass the recording query during failure cleanup: kill-on-close
            # must still reclaim the tree if an assertion or native query fails.
            (original_close or manager._windows_job.close)()


@pytest.mark.skipif(os.name != "nt", reason="Requires real Windows kernel Job Objects")
@pytest.mark.parametrize("transition", ["settings", "import", "shutdown"])
async def test_windows_job_api_reclaims_real_worker_after_parent_exit(
    windows_real_tree, monkeypatch, transition
):
    config, TreeManager, pid_file, exit_file = windows_real_tree
    managers = []

    def factory(config):
        manager = TreeManager(config)
        managers.append(manager)
        return manager

    monkeypatch.setattr("texada.api.LlamaServerManager", factory)
    api = handle = None
    try:
        with TestClient(create_app(config)) as client:
            assert client.post("/api/llama/start").status_code == 200
            api, handle = windows_worker_handle(pid_file)
            exit_file.touch()
            async with asyncio.timeout(3):
                while managers[0]._process.returncode is None:
                    await asyncio.sleep(0.01)
            assert await probe_models_url(config.active_base_url)
            if transition == "settings":
                assert client.post(
                    "/api/settings/backend", json={"backend": "ollama"}
                ).status_code == 200
            elif transition == "import":
                assert client.post(
                    "/api/import", json={"settings": {"backend": "ollama"}}
                ).status_code == 200
        assert api.WaitForSingleObject(handle, 5000) == 0
        assert managers[0]._windows_job is None and managers[0]._process is None
        assert not await probe_models_url(config.active_base_url)
    finally:
        if handle is not None:
            api.CloseHandle(handle)
        if managers and managers[0]._windows_job is not None:
            managers[0]._windows_job.close()
