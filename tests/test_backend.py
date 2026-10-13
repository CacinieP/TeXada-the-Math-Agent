"""Test backend readiness checks."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from texada.config import TeXadaConfig
from texada.core.backend import BackendManager


@pytest.fixture
def models_server():
    """Real loopback HTTP server; a duplicated route must fail readiness."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"data": [{"id": "text"}, {"id": "vision"}]}).encode()
            self.send_response(200 if self.path == "/v1/models" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("host_suffix", ["", "/", "/v1", "/v1/"])
async def test_ollama_probe_and_listing_request_models_route_once(
    tmp_path, models_server, host_suffix
):
    host, requests = models_server
    manager = BackendManager(TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host=host + host_suffix,
        model_name="text",
        vision_model_name="vision",
    ))

    assert await manager._is_running() is True
    assert await manager._list_models() == ["text", "vision"]
    assert requests == [("/v1/models", None)] * 2


@pytest.mark.parametrize("trailing_slash", ["", "/"])
async def test_openai_probe_and_listing_preserve_authorization(
    tmp_path, models_server, trailing_slash
):
    host, requests = models_server
    manager = BackendManager(TeXadaConfig(
        data_dir=tmp_path,
        backend="openai_compatible",
        openai_base_url=host + "/v1" + trailing_slash,
        openai_api_key="test-token",
        openai_model_name="text",
    ))

    assert await manager.ensure_ready() is True
    assert await manager._list_models() == ["text", "vision"]
    assert requests == [("/v1/models", "Bearer test-token")] * 2


@pytest.mark.asyncio
async def test_openai_compatible_requires_endpoint_key_and_model(tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="openai_compatible",
        openai_base_url="",
        openai_api_key="",
        openai_model_name="",
    )
    manager = BackendManager(config)

    with pytest.raises(RuntimeError) as exc:
        await manager.ensure_ready()

    message = str(exc.value)
    assert "endpoint" in message
    assert "api key" in message
    assert "model name" in message


@pytest.mark.asyncio
async def test_ollama_status_reports_partial_ready_for_missing_vision_model(monkeypatch, tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host="localhost:11435",
        model_name="text-model",
        vision_model_name="vision-model",
    )
    manager = BackendManager(config)

    async def is_running():
        return True

    async def list_models():
        return ["text-model"]

    monkeypatch.setattr(manager, "_is_running", is_running)
    monkeypatch.setattr(manager, "_list_models", list_models)
    monkeypatch.setattr("texada.core.backend.shutil.which", lambda _: "/usr/bin/ollama")

    status = await manager.aget_status()

    assert status["status"] == "partial_ready"
    assert status["ready"] is True
    assert status["endpoint"] == "http://localhost:11435/v1"
    assert status["text_model_installed"] is True
    assert status["vision_model_installed"] is False
    assert status["missing_models"] == ["vision-model"]
    assert status["next_action"] == "ollama pull vision-model"


@pytest.mark.asyncio
async def test_ollama_status_reports_missing_text_model(monkeypatch, tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        model_name="text-model",
        vision_model_name="vision-model",
    )
    manager = BackendManager(config)

    async def is_running():
        return True

    async def list_models():
        return ["vision-model"]

    monkeypatch.setattr(manager, "_is_running", is_running)
    monkeypatch.setattr(manager, "_list_models", list_models)
    monkeypatch.setattr("texada.core.backend.shutil.which", lambda _: "/usr/bin/ollama")

    status = await manager.aget_status()

    assert status["status"] == "missing_model"
    assert status["ready"] is False
    assert status["missing_models"] == ["text-model"]
    assert status["next_action"] == "ollama pull text-model"


@pytest.mark.asyncio
async def test_remote_ollama_endpoint_does_not_autostart_local_daemon(monkeypatch, tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host="http://192.168.1.20:11434",
        model_name="text-model",
    )
    manager = BackendManager(config)
    started = False

    async def is_running():
        return False

    async def start_ollama():
        nonlocal started
        started = True

    monkeypatch.setattr(manager, "_is_running", is_running)
    monkeypatch.setattr(manager, "_start_ollama", start_ollama)

    with pytest.raises(RuntimeError) as exc:
        await manager.ensure_ready()

    assert started is False
    assert "Ollama endpoint 不可达" in str(exc.value)
    assert "192.168.1.20:11434" in str(exc.value)


@pytest.mark.asyncio
async def test_remote_ollama_status_points_to_remote_endpoint_check(monkeypatch, tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host="http://192.168.1.20:11434",
        model_name="text-model",
        vision_model_name="vision-model",
    )
    manager = BackendManager(config)

    async def is_running():
        return False

    monkeypatch.setattr(manager, "_is_running", is_running)
    monkeypatch.setattr("texada.core.backend.shutil.which", lambda _: "/usr/bin/ollama")

    status = await manager.aget_status()

    assert status["status"] == "not_running"
    assert status["ready"] is False
    assert status["message"] == "Ollama endpoint 不可达"
    assert status["next_action"] == "启动远端 Ollama，或检查 Ollama 地址和端口"


@pytest.mark.asyncio
async def test_ocr_readiness_does_not_require_text_model(monkeypatch, tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        model_name="missing-text-model",
        vision_model_name="vision-model",
    )
    manager = BackendManager(config)

    async def is_running():
        return True

    async def list_models():
        return ["vision-model"]

    monkeypatch.setattr(manager, "_is_running", is_running)
    monkeypatch.setattr(manager, "_list_models", list_models)

    assert await manager.ensure_vision_ready() is True
