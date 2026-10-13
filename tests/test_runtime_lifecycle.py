"""Owned subprocess cleanup and external-service boundaries, without models."""
from __future__ import annotations

import asyncio
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
