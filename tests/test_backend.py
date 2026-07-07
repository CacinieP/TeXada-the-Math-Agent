"""Test backend readiness checks."""
import pytest

from texada.config import TeXadaConfig
from texada.core.backend import BackendManager


@pytest.mark.asyncio
async def test_openai_compatible_requires_endpoint_key_and_model(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path, backend="openai_compatible")
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
