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

    assert status["status"] == "unverified"
    assert status["ready"] is False
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


@pytest.mark.asyncio
@pytest.mark.parametrize("vision", [False, True])
async def test_llama_unreachable_never_starts_ollama(monkeypatch, tmp_path, vision):
    from unittest.mock import AsyncMock

    manager = BackendManager(TeXadaConfig(data_dir=tmp_path, backend="llama_server"))
    monkeypatch.setattr(manager, "_is_running", AsyncMock(return_value=False))
    starter = AsyncMock()
    monkeypatch.setattr(manager, "_start_ollama", starter)
    with pytest.raises(RuntimeError, match="llama-server endpoint"):
        await (manager.ensure_vision_ready() if vision else manager.ensure_ready())
    starter.assert_not_awaited()


@pytest.mark.asyncio
async def test_llama_readiness_checks_active_models(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    config = TeXadaConfig(data_dir=tmp_path, backend="llama_server")
    manager = BackendManager(config)
    monkeypatch.setattr(manager, "_is_running", AsyncMock(return_value=True))
    monkeypatch.setattr(
        manager,
        "_list_models",
        AsyncMock(return_value=[config.active_model_name, config.active_vision_model_name]),
    )
    assert await manager.ensure_ready()
    assert await manager.ensure_vision_ready()
    monkeypatch.setattr(manager, "_list_models", AsyncMock(return_value=[config.active_model_name]))
    if config.active_model_name != config.active_vision_model_name:
        with pytest.raises(RuntimeError, match="视觉模型不可用"):
            await manager.ensure_vision_ready()


@pytest.mark.asyncio
async def test_llama_status_never_recommends_ollama(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    manager = BackendManager(TeXadaConfig(data_dir=tmp_path, backend="llama_server"))
    monkeypatch.setattr(manager, "_is_running", AsyncMock(return_value=False))
    status = await manager.aget_status()
    assert status["backend"] == "llama_server" and not status["ready"]
    assert "llama-server" in status["next_action"]
    assert "ollama" not in status["next_action"].lower()


@pytest.fixture
def inference_server():
    """Registration succeeds even when loading the projector fails."""
    state = {"fail": True, "posts": 0, "error": "unknown projector type: minicpmv4_7"}

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond(200, {"data": [{"id": "shared"}]})

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["posts"] += 1
            if state["fail"]:
                self.respond(500, {"error": {"message": state["error"]}})
            else:
                self.respond(200, {"id": "test", "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "x"}}
                ]})

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("vision", [False, True])
async def test_registered_model_500_updates_actual_inference_status(
    tmp_path, inference_server, vision,
):
    from texada.core.model import MiniCPMModel

    host, state = inference_server
    config = TeXadaConfig(data_dir=tmp_path, backend="ollama", ollama_host=host,
                          model_name="shared", vision_model_name="shared")
    model = MiniCPMModel(config)
    manager = model.backend
    assert await manager.ensure_ready()
    assert await manager.ensure_vision_ready()
    before = await manager.aget_status()
    assert before["service_reachable"] and before["text_model_installed"]
    assert before["status"] == "unverified" and not before["ready"]
    assert state["posts"] == 0
    kwargs = {"model": "shared", "messages": [{"role": "user", "content": "x"}],
              "max_tokens": 1, "_inference_purpose": "ocr" if vision else "planner"}
    with pytest.raises(RuntimeError, match="内置 llama-server"):
        model._completion_create(**kwargs)
    for _ in range(3):
        status = await manager.aget_status()
        assert status["status"] == "inference_failed" and not status["ready"]
        assert "minicpmv4_7" in status["message"]
        assert "保存" in status["next_action"] and "启动" in status["next_action"]
    assert state["posts"] == 1  # no automatic retries or polling inference
    state["fail"] = False
    model._completion_create(**kwargs)
    status = await manager.aget_status()
    role = "vision" if vision else "text"
    other = "text" if vision else "vision"
    assert status[f"{role}_inference_status"] == "verified"
    assert status[f"{other}_inference_status"] == "unverified"
    assert status["status"] != "ready"  # text cannot certify OCR, or vice versa
    model._completion_create(**{**kwargs, "_inference_purpose": "planner" if vision else "ocr"})
    assert (await manager.aget_status())["status"] == "ready"


async def test_inference_observations_expire_and_do_not_cross_settings(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    manager = BackendManager(TeXadaConfig(data_dir=tmp_path, backend="ollama",
                                         model_name="shared", vision_model_name="shared"))
    monkeypatch.setattr(manager, "_is_running", AsyncMock(return_value=True))
    monkeypatch.setattr(manager, "_list_models", AsyncMock(return_value=["shared"]))
    monkeypatch.setattr("texada.core.backend.time.monotonic", lambda: 100)
    manager.record_inference("shared", vision=False)
    assert (await manager.aget_status())["ready"]
    manager.config.ollama_host = "http://localhost:11435"
    assert not (await manager.aget_status())["ready"]
    manager.config.ollama_host = "http://localhost:11434"
    monkeypatch.setattr("texada.core.backend.time.monotonic", lambda: 401)
    assert not (await manager.aget_status())["ready"]


async def test_api_status_observes_router_inference_failure(tmp_path, inference_server):
    from fastapi.testclient import TestClient

    from texada.api import create_app

    host, state = inference_server
    config = TeXadaConfig(data_dir=tmp_path, backend="ollama", ollama_host=host,
                          model_name="shared", vision_model_name="shared")
    with TestClient(create_app(config)) as client:
        before = client.get("/api/status").json()
        assert before["status"] == "unverified" and not before["ready"]
        assert before["service_reachable"] and before["text_model_installed"]
        response = client.post("/api/convert", json={"text": "写出正态分布的概率密度函数"})
        assert response.status_code == 503
        assert "minicpmv4_7" in response.json()["detail"]
        after = client.get("/api/status").json()
        assert after["status"] == "inference_failed" and not after["ready"]
        assert after["text_inference_status"] == "failed"
        assert state["posts"] == 1


async def test_generic_500_does_not_claim_projector_diagnosis(tmp_path, inference_server):
    from texada.core.model import MiniCPMModel

    host, state = inference_server
    state["error"] = "runner process has terminated"
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path, backend="ollama", ollama_host=host,
                                    model_name="shared", vision_model_name="shared"))
    with pytest.raises(RuntimeError, match="若包含 unknown projector type"):
        model._completion_create(model="shared", messages=[{"role": "user", "content": "x"}])
    status = await model.backend.aget_status()
    assert not status["ready"] and status["text_inference_status"] == "failed"
    assert state["posts"] == 1
