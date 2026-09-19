"""Downloader tests — mocked streaming responses, no network."""
from __future__ import annotations

import httpx
import pytest

from texada.core.download import DownloadError, download_model


class FakeStreamResponse:
    def __init__(self, chunks, status_code=200, headers=None):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}

    async def aiter_bytes(self, _size):
        for chunk in self._chunks:
            yield chunk


class FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    def __init__(self, chunks, status_code=200, headers=None, error=None):
        self._chunks = chunks
        self._status_code = status_code
        self._headers = headers
        self._error = error
        self.requested_urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url):
        self.requested_urls.append(url)
        if self._error:
            raise self._error
        return FakeStreamCM(
            FakeStreamResponse(self._chunks, self._status_code, self._headers)
        )


def _client_factory(client):
    return lambda: client


async def test_download_yields_progress_and_completes(tmp_path):
    chunks = [b"x" * 10, b"y" * 10]
    client = FakeClient(chunks, headers={"Content-Length": "20"})
    events = [
        e async for e in download_model(
            "text", tmp_path, client_factory=_client_factory(client)
        )
    ]
    assert len(events) >= 3
    assert events[0]["received"] == 10
    assert events[1]["received"] == 20
    assert events[-1]["done"] is True
    assert events[-1]["error"] is None
    final = tmp_path / "MiniCPM5-2B-Q4_K_M.gguf"
    assert final.is_file()
    assert final.read_bytes() == b"x" * 10 + b"y" * 10
    assert not list(tmp_path.glob("*.part"))


async def test_existing_file_is_skipped(tmp_path):
    name = "MiniCPM5-2B-Q4_K_M.gguf"
    (tmp_path / name).write_bytes(b"already")
    client = FakeClient([])
    events = [
        e async for e in download_model(
            "text", tmp_path, client_factory=_client_factory(client)
        )
    ]
    assert len(events) == 1
    assert events[0]["skipped"] is True
    assert client.requested_urls == []


async def test_http_error_leaves_no_complete_file(tmp_path):
    client = FakeClient([b"x"], status_code=404)
    events = [
        e async for e in download_model(
            "text", tmp_path, client_factory=_client_factory(client)
        )
    ]
    assert events[-1]["error"] is not None
    assert "404" in events[-1]["error"]
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.gguf"))


async def test_incomplete_download_is_rejected(tmp_path):
    client = FakeClient([b"x" * 5], headers={"Content-Length": "100"})
    events = [
        e async for e in download_model(
            "text", tmp_path, client_factory=_client_factory(client)
        )
    ]
    assert events[-1]["error"] is not None
    assert "不完整" in events[-1]["error"]
    assert not list(tmp_path.glob("*.part"))


async def test_vision_role_downloads_two_files(tmp_path):
    client = FakeClient([b"a"], headers={"Content-Length": "1"})
    events = [
        e async for e in download_model(
            "vision", tmp_path, client_factory=_client_factory(client)
        )
    ]
    done = [e for e in events if e["done"] and not e["skipped"]]
    assert len(done) == 2
    assert (tmp_path / "MiniCPM-V-4_6-Q4_K_M.gguf").is_file()
    assert (tmp_path / "mmproj-model-f16.gguf").is_file()


async def test_unknown_role_is_rejected(tmp_path):
    with pytest.raises(DownloadError):
        _ = [e async for e in download_model("bogus", tmp_path)]


async def test_mirror_uses_mirror_base_url(tmp_path):
    client = FakeClient([b"a"], headers={"Content-Length": "1"})
    _ = [
        e async for e in download_model(
            "text", tmp_path, mirror=True, client_factory=_client_factory(client)
        )
    ]
    assert client.requested_urls[0].startswith("https://hf-mirror.com/")


async def test_network_exception_is_reported(tmp_path):
    client = FakeClient([], error=httpx.ConnectError("boom"))
    events = [
        e async for e in download_model(
            "text", tmp_path, client_factory=_client_factory(client)
        )
    ]
    assert events[-1]["error"] is not None
    assert not list(tmp_path.glob("*.part"))
