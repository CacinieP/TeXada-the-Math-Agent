"""Independent text/OCR credentials must follow the intended role, including retries."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.inference_fingerprint import build_inference_identity
from texada.core.model import MiniCPMModel


def config(tmp_path, **overrides):
    values = dict(
        data_dir=tmp_path, backend="openai_compatible",
        openai_base_url="https://text.test/v1", openai_api_key="text-only-secret",
        openai_model_name="text-model", openai_vision_base_url="https://ocr.test/v1/",
        openai_vision_api_key="ocr-only-secret", openai_vision_model_name="ocr-model",
    )
    return TeXadaConfig(**(values | overrides))


def test_legacy_shared_connection_and_explicit_same_endpoint_remain_compatible(tmp_path):
    cfg = config(tmp_path, openai_vision_base_url="", openai_vision_api_key="",
                 openai_vision_model_name="")
    assert cfg.active_vision_base_url == cfg.active_base_url
    assert cfg.active_vision_api_key == cfg.active_api_key
    assert cfg.active_vision_model_name == cfg.active_model_name
    same = config(tmp_path, openai_vision_base_url="https://text.test/v1/",
                  openai_vision_api_key="")
    assert same.active_vision_api_key == cfg.active_api_key


def test_different_ocr_service_never_inherits_text_secret_or_model(tmp_path):
    cfg = config(tmp_path, openai_vision_api_key="", openai_vision_model_name="")
    assert cfg.active_vision_api_key == ""
    assert cfg.active_vision_model_name == ""
    model = MiniCPMModel(cfg)
    with pytest.raises(RuntimeError, match="API key"):
        _ = model.vision_client
    assert model._client is None and model._vision_client is None


@pytest.mark.asyncio
async def test_text_and_ocr_retry_use_their_own_three_connection_values(tmp_path, monkeypatch):
    requests = []
    attempts = 0

    def respond(request):
        nonlocal attempts
        body = json.loads(request.content)
        requests.append((request.url.host, request.headers["authorization"], body["model"]))
        if request.url.host == "ocr.test":
            attempts += 1
            content = "" if attempts == 1 else r"\frac{x}{y}"
        else:
            content = "x+y"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    original_client = httpx.Client
    class MockClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("texada.core.model.httpx.Client", MockClient)
    model = MiniCPMModel(config(tmp_path))
    try:
        assert await model.generate_latex("x plus y", "generic") == "x+y"
        assert await model.ocr_latex(b"test-image") == r"\frac{x}{y}"
    finally:
        if model._client:
            model._client.close()
        if model._vision_client:
            model._vision_client.close()
    assert requests == [
        ("text.test", "Bearer text-only-secret", "text-model"),
        ("ocr.test", "Bearer ocr-only-secret", "ocr-model"),
        ("ocr.test", "Bearer ocr-only-secret", "ocr-model"),
    ]


@pytest.mark.asyncio
async def test_ocr_readiness_is_not_satisfied_by_cached_text_readiness(tmp_path, monkeypatch):
    calls = []

    async def probe(url, headers=None, **kwargs):
        calls.append((url, headers))
        return url == "https://text.test/v1"

    monkeypatch.setattr("texada.core.backend.probe_models_url", probe)
    manager = BackendManager(config(tmp_path))
    assert await manager.ensure_ready()
    with pytest.raises(RuntimeError, match="OCR"):
        await manager.ensure_vision_ready()
    status = await manager.aget_status()
    assert status["status"] == "partial_ready"
    assert status["text_model_installed"] is True
    assert status["vision_model_installed"] is False
    assert ("https://ocr.test/v1", {"Authorization": "Bearer ocr-only-secret"}) in calls
    assert not any(url == "https://ocr.test/v1" and "text-only-secret" in str(headers)
                   for url, headers in calls)


def test_both_credentials_persist_but_never_appear_in_settings_or_backup(tmp_path):
    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))
    payload = {k: v for k, v in config(tmp_path).model_dump().items()
               if k.startswith("openai_")}
    payload["backend"] = "openai_compatible"
    response = client.post("/api/settings/backend", json=payload)
    assert response.status_code == 200
    assert response.json()["openai_vision_base_url"] == "https://ocr.test/v1"
    assert response.json()["openai_vision_api_key_set"] is True
    assert client.post("/api/settings/backend", json={
        "openai_api_key": "", "openai_vision_api_key": "",
    }).status_code == 200
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["openai_api_key"] == "text-only-secret"
    assert saved["openai_vision_api_key"] == "ocr-only-secret"
    for path in ("/api/settings/backend", "/api/export"):
        serialized = client.get(path).text
        assert "text-only-secret" not in serialized
        assert "ocr-only-secret" not in serialized
    assert client.get("/api/export").json()["settings"]["openai_vision_base_url"] == "https://ocr.test/v1"


def test_fingerprint_records_sanitized_ocr_endpoint_without_either_key(tmp_path):
    identity = build_inference_identity(config(
        tmp_path, openai_vision_base_url="https://user:password@ocr.test/v1?api_key=hidden",
    ))
    assert identity["endpoint"] == "https://text.test/v1"
    assert identity["vision_endpoint"] == "https://ocr.test/v1"
    serialized = json.dumps(identity)
    assert all(secret not in serialized for secret in (
        "text-only-secret", "ocr-only-secret", "password", "hidden",
    ))
