"""Streaming model downloader for the llama-server runtime.

Downloads GGUF weights (and the vision projector) from Hugging Face into
the configured models directory. Writes to a ``.part`` file and renames on
completion, so an interrupted download never masquerades as a model.
Yields progress events for the API/UI layer.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, NamedTuple

import httpx

from texada.core.llama_server import (
    TEXT_MODEL_FILE,
    VISION_MMPROJ_FILE,
    VISION_MODEL_FILE,
)

HF_BASE = "https://huggingface.co"
HF_MIRROR_BASE = "https://hf-mirror.com"
CHUNK_SIZE = 1024 * 1024
HTTP_TIMEOUT = httpx.Timeout(30.0, read=300.0)
HASH_CHUNK = 1024 * 1024


class ModelFile(NamedTuple):
    """One downloadable artifact, pinned to the publisher's SHA-256."""

    local_name: str
    remote_name: str
    sha256: str


# role -> (repo id, [ModelFile])
MODEL_CATALOG: dict[str, tuple[str, list[ModelFile]]] = {
    "text": (
        "openbmb/MiniCPM5-2B-GGUF",
        [
            ModelFile(
                TEXT_MODEL_FILE,
                "MiniCPM5-2B-Q4_K_M.gguf",
                "ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd",
            )
        ],
    ),
    "vision": (
        "openbmb/MiniCPM-V-4.6-gguf",
        [
            ModelFile(
                VISION_MODEL_FILE,
                "MiniCPM-V-4_6-Q4_K_M.gguf",
                "6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2",
            ),
            ModelFile(
                VISION_MMPROJ_FILE,
                "mmproj-model-f16.gguf",
                "ca931d861d0801d9003e50697cd764721a334107c0e0415a51168ee1938462de",
            ),
        ],
    ),
}

ClientFactory = Callable[[], httpx.AsyncClient]


class DownloadError(RuntimeError):
    """Raised when a model download cannot complete."""


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 so multi-GB weights never land in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


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

    Yields events: {"file", "received", "total", "done", "skipped", "error"}.
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
                    "error": None,
                }
                continue

            part_path = final_path.with_suffix(final_path.suffix + ".part")
            url = f"{base}/{repo}/resolve/main/{spec.remote_name}"
            received = 0
            total: int | None = None
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise DownloadError(f"下载失败 HTTP {resp.status_code}: {url}")
                    length = resp.headers.get("Content-Length")
                    if length and length.isdigit():
                        total = int(length)
                    with part_path.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                            fh.write(chunk)
                            received += len(chunk)
                            yield {
                                "file": spec.local_name,
                                "received": received,
                                "total": total,
                                "done": False,
                                "skipped": False,
                                "error": None,
                            }
            except Exception as exc:
                part_path.unlink(missing_ok=True)
                yield {
                    "file": spec.local_name,
                    "received": received,
                    "total": total,
                    "done": False,
                    "skipped": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                return

            if total is not None and received != total:
                part_path.unlink(missing_ok=True)
                yield {
                    "file": spec.local_name,
                    "received": received,
                    "total": total,
                    "done": False,
                    "skipped": False,
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
                "error": None,
            }


async def download_all(dest_dir: Path, *, mirror: bool = False) -> AsyncIterator[dict[str, Any]]:
    """Download text and vision roles in sequence."""
    for role in ("text", "vision"):
        async for event in download_model(role, dest_dir, mirror=mirror):
            yield {**event, "role": role}
