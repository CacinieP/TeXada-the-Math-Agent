"""Streaming model downloader for the llama-server runtime.

Downloads GGUF weights (and the vision projector) from Hugging Face into
the configured models directory. Writes to a ``.part`` file and renames on
completion, so an interrupted download never masquerades as a model.
Yields progress events for the API/UI layer.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from pathlib import Path
from typing import Any, NamedTuple

import httpx

from texada.core.llama_server import (
    PINNED_SHA256,
    TEXT_MODEL_FILE,
    VISION_MMPROJ_FILE,
    sha256_file,
)

HF_BASE = "https://huggingface.co"
HF_MIRROR_BASE = "https://hf-mirror.com"
HTTP_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)$")


class ModelFile(NamedTuple):
    """One downloadable artifact, pinned to the publisher's SHA-256."""

    local_name: str
    remote_name: str
    sha256: str


# role -> (repo id, [ModelFile])
MODEL_REVISION = "59cd286146b6ce70f818508ccf512e11438d8957"
WEIGHTS = ModelFile(
    TEXT_MODEL_FILE, TEXT_MODEL_FILE, PINNED_SHA256[TEXT_MODEL_FILE],
)
PROJECTOR = ModelFile(
    VISION_MMPROJ_FILE, VISION_MMPROJ_FILE, PINNED_SHA256[VISION_MMPROJ_FILE],
)
MODEL_CATALOG: dict[str, tuple[str, list[ModelFile]]] = {
    "text": ("openbmb/MiniCPM-V-4.7-1B-gguf", [WEIGHTS]),
    "vision": ("openbmb/MiniCPM-V-4.7-1B-gguf", [WEIGHTS, PROJECTOR]),
}

ClientFactory = Callable[[], httpx.AsyncClient]


class DownloadError(RuntimeError):
    """Raised when a model download cannot complete."""


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT, trust_env=False, follow_redirects=True)


async def download_model(
    role: str,
    dest_dir: Path,
    *,
    mirror: bool = False,
    client_factory: ClientFactory | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Download every file for ``role`` into ``dest_dir``.

    Yields events: {"file", "received", "total", "done", "skipped",
    "resumed", "error"}. An existing ``.part`` file is resumed with an HTTP
    Range request; a server that ignores or rejects the range restarts the
    file from scratch instead of appending misaligned bytes.
    """
    if role not in MODEL_CATALOG:
        raise DownloadError(f"未知模型角色: {role}")
    repo, files = MODEL_CATALOG[role]
    base = HF_MIRROR_BASE if mirror else HF_BASE
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    factory = client_factory or _default_client_factory

    async with factory() as client:
        for spec in files:
            final_path = dest_dir / spec.local_name
            expected = spec.sha256
            if final_path.is_file() and (not expected or sha256_file(final_path) == expected):
                size = final_path.stat().st_size
                yield {
                    "file": spec.local_name,
                    "received": size,
                    "total": size,
                    "done": True,
                    "skipped": True,
                    "resumed": False,
                    "error": None,
                }
                continue

            part_path = final_path.with_suffix(final_path.suffix + ".part")
            url = f"{base}/{repo}/resolve/{MODEL_REVISION}/{spec.remote_name}"
            received = 0
            total: int | None = None
            resumed = False
            try:
                for attempt in (0, 1):
                    existing = part_path.stat().st_size if part_path.is_file() else 0
                    use_range = attempt == 0 and existing > 0
                    headers = {"Range": f"bytes={existing}-"} if use_range else {}
                    async with client.stream("GET", url, headers=headers) as resp:
                        content_range = (resp.headers.get("Content-Range") or "").strip()
                        range_match = _CONTENT_RANGE.match(content_range)
                        range_total: int | None = None
                        body_length: int | None = None
                        if resp.status_code == 206 and range_match:
                            start, end, size = map(int, range_match.groups())
                            length = resp.headers.get("Content-Length")
                            if (start == (existing if use_range else 0)
                                    and start <= end < size
                                    and (length is None or length == str(end - start + 1))):
                                range_total = size
                                body_length = end - start + 1
                        if resp.status_code == 416 or (
                            resp.status_code == 206 and range_total is None
                        ):
                            # A partial that cannot be resumed is worse than
                            # none: drop it and retry with a plain request.
                            part_path.unlink(missing_ok=True)
                            if attempt == 0:
                                continue
                            raise DownloadError(f"下载失败 HTTP {resp.status_code}: {url}")
                        if resp.status_code not in (200, 206):
                            raise DownloadError(f"下载失败 HTTP {resp.status_code}: {url}")
                        if range_total is not None:
                            total = range_total
                            received = existing
                            resumed = use_range
                            mode = "ab" if use_range else "wb"
                        else:
                            length = resp.headers.get("Content-Length")
                            total = int(length) if length and length.isdigit() else None
                            received = 0
                            mode = "wb"
                            body_length = total
                        body_received = 0
                        with part_path.open(mode) as fh:
                            # Do not aggregate small transport chunks: a read
                            # failure must not lose an already received prefix.
                            async for chunk in resp.aiter_bytes(None):
                                if (body_length is not None
                                        and body_received + len(chunk) > body_length):
                                    # Never retain bytes outside the validated
                                    # response range, even on cancellation.
                                    fh.close()
                                    part_path.unlink(missing_ok=True)
                                    raise DownloadError("下载内容超过声明长度，已丢弃无效分片")
                                fh.write(chunk)
                                body_received += len(chunk)
                                received += len(chunk)
                                yield {
                                    "file": spec.local_name,
                                    "received": received,
                                    "total": total,
                                    "done": False,
                                    "skipped": False,
                                    "resumed": resumed,
                                    "error": None,
                                }
                    break
            except Exception as exc:
                # A transport interruption leaves a contiguous prefix of the
                # pinned resource. Keep it for a later Range request; only a
                # complete file passing the pinned hash may be published.
                yield {
                    "file": spec.local_name,
                    "received": received,
                    "total": total,
                    "done": False,
                    "skipped": False,
                    "resumed": resumed,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                return

            if total is not None and received != total:
                if received > total:
                    part_path.unlink(missing_ok=True)
                yield {
                    "file": spec.local_name,
                    "received": received,
                    "total": total,
                    "done": False,
                    "skipped": False,
                    "resumed": resumed,
                    "error": f"下载不完整: {received}/{total} 字节",
                }
                return

            # Right size does not mean right bytes: a truncated or mis-assembled
            # stream still yields the expected length. Verify before publishing.
            if expected and sha256_file(part_path) != expected:
                part_path.unlink(missing_ok=True)
                yield {
                    "file": spec.local_name,
                    "received": received,
                    "total": total,
                    "done": False,
                    "skipped": False,
                    "resumed": resumed,
                    "error": "校验和不匹配，模型文件已损坏，请重试下载",
                }
                return

            part_path.replace(final_path)
            yield {
                "file": spec.local_name,
                "received": received,
                "total": total,
                "done": True,
                "skipped": False,
                "resumed": resumed,
                "error": None,
            }


async def download_all(dest_dir: Path, *, mirror: bool = False) -> AsyncIterator[dict[str, Any]]:
    """Download both roles and emit one explicit terminal result.

    An error short-circuits the sequence. Cancellation/disconnect propagates
    without inventing a terminal event, leaving the current prefix resumable.
    """
    try:
        for role in ("text", "vision"):
            async with aclosing(download_model(role, dest_dir, mirror=mirror)) as events:
                async for event in events:
                    yield {**event, "role": role}
                    if event.get("error"):
                        yield {"all_done": True, "success": False, "error": event["error"]}
                        return
    except Exception as exc:
        yield {"all_done": True, "success": False, "error": f"{type(exc).__name__}: {exc}"}
        return
    yield {"all_done": True, "success": True}
