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
