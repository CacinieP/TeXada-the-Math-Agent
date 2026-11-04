"""Real HTTPX streaming boundaries: resume prefixes and explicit pull outcome."""

import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from texada.core import download


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, error=None, waiting=None):
        self.chunks, self.error, self.waiting = chunks, error, waiting
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error
        if self.waiting:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.fixture
def payload(monkeypatch):
    value = b"0123456789abcdef"
    digest = hashlib.sha256(value).hexdigest()
    for role, (repo, files) in download.MODEL_CATALOG.items():
        monkeypatch.setitem(
            download.MODEL_CATALOG,
            role,
            (repo, [download.ModelFile(f.local_name, f.remote_name, digest) for f in files]),
        )
    return value


def factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def part(tmp_path):
    return tmp_path / (download.TEXT_MODEL_FILE + ".part")


@pytest.mark.parametrize("interrupted", [True, False], ids=["read-error", "short-eof"])
async def test_interrupted_httpx_prefix_is_resumed_and_published_only_after_pin(
    tmp_path,
    payload,
    interrupted,
):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                headers={"Content-Length": str(len(payload))},
                stream=Stream(
                    [payload[:3], payload[3:7]],
                    error=httpx.ReadError("link dropped") if interrupted else None,
                ),
            )
        assert request.headers["Range"] == "bytes=7-"
        return httpx.Response(
            206,
            headers={"Content-Range": "bytes 7-15/16", "Content-Length": "9"},
            stream=Stream([payload[7:]]),
        )

    first = [
        event
        async for event in download.download_model(
            "text", tmp_path, client_factory=factory(handler)
        )
    ]
    assert first[-1]["error"] and not first[-1]["done"]
    assert part(tmp_path).read_bytes() == payload[:7]
    assert not (tmp_path / download.TEXT_MODEL_FILE).exists()
    second = [
        event
        async for event in download.download_model(
            "text", tmp_path, client_factory=factory(handler)
        )
    ]
    assert len(requests) == 2 and "Range" not in requests[0].headers
    assert second[-1]["done"] and second[-1]["resumed"] and second[-1]["error"] is None
    assert (tmp_path / download.TEXT_MODEL_FILE).read_bytes() == payload
    assert not part(tmp_path).exists()


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "16"}])
async def test_hash_mismatch_never_publishes_or_retains_corrupt_prefix(tmp_path, payload, headers):
    events = [
        event
        async for event in download.download_model(
            "text",
            tmp_path,
            client_factory=factory(
                lambda _: httpx.Response(200, headers=headers, stream=Stream([b"x" * len(payload)]))
            ),
        )
    ]
    assert "校验" in events[-1]["error"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("ranged", [False, True])
async def test_overlong_response_discards_partial_before_error(tmp_path, payload, ranged):
    if ranged:
        part(tmp_path).write_bytes(payload[:7])
    headers = (
        {"Content-Range": "bytes 7-15/16", "Content-Length": "9"}
        if ranged
        else {"Content-Length": "16"}
    )
    response = httpx.Response(
        206 if ranged else 200,
        headers=headers,
        stream=Stream([payload[7:] if ranged else payload, b"extra"]),
    )
    events = [
        event
        async for event in download.download_model(
            "text", tmp_path, client_factory=factory(lambda _: response)
        )
    ]
    assert "超过" in events[-1]["error"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "content_range,length",
    [
        ("bytes 8-15/16", "8"),
        ("bytes 7-16/16", "10"),
        ("bytes 7-6/16", "0"),
        ("bytes 7-15/0", "9"),
        ("bytes 7-15/16", "8"),
        ("not a range", "9"),
    ],
)
async def test_invalid_range_is_discarded_even_when_full_retry_is_interrupted(
    tmp_path,
    payload,
    content_range,
    length,
):
    part(tmp_path).write_bytes(payload[:7])
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                206,
                headers={"Content-Range": content_range, "Content-Length": length},
                stream=Stream([b"untrusted"]),
            )
        assert "Range" not in request.headers
        raise httpx.ConnectError("full retry unavailable")

    events = [
        event
        async for event in download.download_model(
            "text", tmp_path, client_factory=factory(handler)
        )
    ]
    assert len(requests) == 2 and events[-1]["error"]
    assert not list(tmp_path.iterdir())


async def test_cancellation_preserves_prefix_and_does_not_emit_terminal(
    tmp_path, payload, monkeypatch
):
    waiting = asyncio.Event()
    stream = Stream([payload[:5]], waiting=waiting)
    monkeypatch.setattr(
        download,
        "_default_client_factory",
        factory(lambda _: httpx.Response(200, headers={"Content-Length": "16"}, stream=stream)),
    )
    events = []

    async def consume():
        async for event in download.download_all(tmp_path):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(waiting.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and part(tmp_path).read_bytes() == payload[:5]
    assert not (tmp_path / download.TEXT_MODEL_FILE).exists()
    assert events and not any(event.get("all_done") for event in events)


async def test_closing_consumer_after_progress_closes_stream_and_keeps_prefix(
    tmp_path,
    payload,
    monkeypatch,
):
    stream = Stream([payload[:5], payload[5:]])
    monkeypatch.setattr(
        download,
        "_default_client_factory",
        factory(lambda _: httpx.Response(200, headers={"Content-Length": "16"}, stream=stream)),
    )
    events = download.download_all(tmp_path)
    first = await anext(events)
    assert first["received"] == 5 and not first.get("all_done")
    await events.aclose()
    assert stream.closed and part(tmp_path).read_bytes() == payload[:5]
    assert not (tmp_path / download.TEXT_MODEL_FILE).exists()


@pytest.mark.parametrize("cached", [False, True], ids=["real-httpx-download", "all-cached"])
async def test_all_roles_have_one_success_terminal_after_every_file(
    tmp_path, payload, monkeypatch, cached
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"Content-Length": "16"}, stream=Stream([payload]))

    if cached:
        for name in (download.TEXT_MODEL_FILE, download.VISION_MMPROJ_FILE):
            (tmp_path / name).write_bytes(payload)
    monkeypatch.setattr(download, "_default_client_factory", factory(handler))
    events = [event async for event in download.download_all(tmp_path)]
    assert events[-1] == {"all_done": True, "success": True}
    assert sum(bool(event.get("all_done")) for event in events) == 1
    assert len([event for event in events if event.get("done")]) == 3
    assert len(requests) == (0 if cached else 2)
    assert all(
        (tmp_path / name).read_bytes() == payload
        for name in (download.TEXT_MODEL_FILE, download.VISION_MMPROJ_FILE)
    )


async def test_file_error_short_circuits_roles_and_preserves_terminal_error(
    tmp_path, payload, monkeypatch
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, stream=Stream([]))

    monkeypatch.setattr(download, "_default_client_factory", factory(handler))
    events = [event async for event in download.download_all(tmp_path)]
    assert len(requests) == 1 and len(events) == 2
    assert events[0]["role"] == "text" and events[0]["error"]
    assert events[-1] == {"all_done": True, "success": False, "error": events[0]["error"]}


async def test_client_initialization_failure_is_explicit_terminal(tmp_path, monkeypatch):
    def fail():
        raise RuntimeError("client unavailable")

    monkeypatch.setattr(download, "_default_client_factory", fail)
    events = [event async for event in download.download_all(tmp_path)]
    assert events == [
        {"all_done": True, "success": False, "error": "RuntimeError: client unavailable"}
    ]


def test_installed_api_contract_serializes_terminal_as_final_ndjson(tmp_path, payload, monkeypatch):
    from texada.api import create_app
    from texada.config import TeXadaConfig

    monkeypatch.setattr(
        download,
        "_default_client_factory",
        factory(
            lambda _: httpx.Response(
                200, headers={"Content-Length": "16"}, stream=Stream([payload])
            )
        ),
    )
    with TestClient(create_app(TeXadaConfig(data_dir=tmp_path, backend="llama_server"))) as client:
        response = client.post("/api/llama/pull", json={"mirror": False})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1] == {"all_done": True, "success": True}
    assert sum(bool(event.get("all_done")) for event in events) == 1
