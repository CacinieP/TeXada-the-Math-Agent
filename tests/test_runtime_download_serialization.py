"""Concurrent API streams cannot write the same partial model files."""
import asyncio

import httpx
import pytest

from texada.api import create_app
from texada.config import TeXadaConfig


@pytest.mark.asyncio
async def test_model_download_requests_are_serialized(monkeypatch, tmp_path):
    active = 0
    peak = 0
    completed = 0

    async def fake_download(dest_dir, *, mirror=False):
        nonlocal active, peak, completed
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            yield {"file": "model.gguf", "done": True, "error": None}
            completed += 1
        finally:
            active -= 1

    monkeypatch.setattr("texada.api.download_all", fake_download)
    app = create_app(TeXadaConfig(data_dir=tmp_path, backend="llama_server"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        results = await asyncio.gather(*[client.post("/api/llama/pull", json={}) for _ in range(2)])
    assert all(r.status_code == 200 and '"done": true' in r.text for r in results)
    assert peak == 1 and completed == 2 and active == 0
