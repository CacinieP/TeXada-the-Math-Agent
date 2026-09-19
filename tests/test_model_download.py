"""Downloader tests — mocked streaming responses, no network."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from texada.core.download import (
    MODEL_CATALOG,
    DownloadError,
    ModelFile,
    download_model,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trust_catalog(monkeypatch, payload: bytes, role: str = "text") -> None:
    """Point every file of ``role`` at the SHA-256 of the mocked payload."""
    repo, files = MODEL_CATALOG[role]
    patched = [ModelFile(f.local_name, f.remote_name, _sha(payload)) for f in files]
    monkeypatch.setitem(MODEL_CATALOG, role, (repo, patched))


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
        return FakeStreamCM(FakeStreamResponse(self._chunks, self._status_code, self._headers))


def _client_factory(client):
    return lambda: client


async def test_download_yields_progress_and_completes(tmp_path, monkeypatch):
    payload = b"x" * 10 + b"y" * 10
    _trust_catalog(monkeypatch, payload)
    client = FakeClient([b"x" * 10, b"y" * 10], headers={"Content-Length": "20"})
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
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


async def test_corrupt_download_is_rejected_by_checksum(tmp_path, monkeypatch):
    """A right-sized but wrong-content file must never become the model."""
    _trust_catalog(monkeypatch, b"expected bytes")
    client = FakeClient([b"corrupt bytes"], headers={"Content-Length": "13"})
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert events[-1]["error"] is not None
    assert "校验" in events[-1]["error"]
    assert not list(tmp_path.glob("*.gguf"))
    assert not list(tmp_path.glob("*.part"))


async def test_existing_file_with_wrong_checksum_is_redownloaded(tmp_path, monkeypatch):
    """An existing file is only skipped when its checksum is known good."""
    payload = b"good weights"
    _trust_catalog(monkeypatch, payload)
    (tmp_path / "MiniCPM5-2B-Q4_K_M.gguf").write_bytes(b"bad weights!!")
    client = FakeClient([payload], headers={"Content-Length": str(len(payload))})
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert client.requested_urls, "a corrupt model must be re-downloaded"
    assert not any(e["skipped"] for e in events)
    final = tmp_path / "MiniCPM5-2B-Q4_K_M.gguf"
    assert final.read_bytes() == payload
    assert events[-1]["error"] is None


async def test_existing_file_with_matching_checksum_is_skipped(tmp_path, monkeypatch):
    payload = b"good weights"
    _trust_catalog(monkeypatch, payload)
    (tmp_path / "MiniCPM5-2B-Q4_K_M.gguf").write_bytes(payload)
    client = FakeClient([])
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert len(events) == 1
    assert events[0]["skipped"] is True
    assert client.requested_urls == []


async def test_http_error_leaves_no_complete_file(tmp_path, monkeypatch):
    _trust_catalog(monkeypatch, b"x")
    client = FakeClient([b"x"], status_code=404)
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert events[-1]["error"] is not None
    assert "404" in events[-1]["error"]
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.gguf"))


async def test_incomplete_download_is_rejected(tmp_path, monkeypatch):
    _trust_catalog(monkeypatch, b"x" * 100)
    client = FakeClient([b"x" * 5], headers={"Content-Length": "100"})
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert events[-1]["error"] is not None
    assert "不完整" in events[-1]["error"]
    assert not list(tmp_path.glob("*.part"))


async def test_vision_role_downloads_two_files(tmp_path, monkeypatch):
    _trust_catalog(monkeypatch, b"a", role="vision")
    client = FakeClient([b"a"], headers={"Content-Length": "1"})
    events = [
        e async for e in download_model("vision", tmp_path, client_factory=_client_factory(client))
    ]
    done = [e for e in events if e["done"] and not e["skipped"]]
    assert len(done) == 2
    assert (tmp_path / "MiniCPM-V-4_6-Q4_K_M.gguf").is_file()
    assert (tmp_path / "mmproj-model-f16.gguf").is_file()


async def test_unknown_role_is_rejected(tmp_path):
    with pytest.raises(DownloadError):
        _ = [e async for e in download_model("bogus", tmp_path)]


async def test_mirror_uses_mirror_base_url(tmp_path, monkeypatch):
    _trust_catalog(monkeypatch, b"a")
    client = FakeClient([b"a"], headers={"Content-Length": "1"})
    _ = [
        e
        async for e in download_model(
            "text", tmp_path, mirror=True, client_factory=_client_factory(client)
        )
    ]
    assert client.requested_urls[0].startswith("https://hf-mirror.com/")


async def test_network_exception_is_reported(tmp_path, monkeypatch):
    _trust_catalog(monkeypatch, b"")
    client = FakeClient([], error=httpx.ConnectError("boom"))
    events = [
        e async for e in download_model("text", tmp_path, client_factory=_client_factory(client))
    ]
    assert events[-1]["error"] is not None
    assert not list(tmp_path.glob("*.part"))
