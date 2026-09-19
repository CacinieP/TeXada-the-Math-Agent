"""Streaming model downloader for the llama-server runtime.

Downloads GGUF weights (and the vision projector) from Hugging Face into
the configured models directory. Writes to a ``.part`` file and renames on
completion, so an interrupted download never masquerades as a model.
Yields progress events for the API/UI layer.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

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

# role -> (repo id, [(local filename, remote filename)])
MODEL_CATALOG: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "text": (
        "openbmb/MiniCPM5-2B-GGUF",
        [(TEXT_MODEL_FILE, "MiniCPM5-2B-Q4_K_M.gguf")],
    ),
    "vision": (
        "openbmb/MiniCPM-V-4.6-gguf",
        [
            (VISION_MODEL_FILE, "MiniCPM-V-4_6-Q4_K_M.gguf"),
            (VISION_MMPROJ_FILE, "mmproj-model-f16.gguf"),
        ],
    ),
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
        for local_name, remote_name in files:
            final_path = dest_dir / local_name
            if final_path.is_file() and final_path.stat().st_size > 0:
                size = final_path.stat().st_size
                yield {
                    "file": local_name, "received": size, "total": size,
                    "done": True, "skipped": True, "error": None,
                }
                continue

            part_path = final_path.with_suffix(final_path.suffix + ".part")
            url = f"{base}/{repo}/resolve/main/{remote_name}"
            received = 0
            total: int | None = None
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise DownloadError(
                            f"下载失败 HTTP {resp.status_code}: {url}"
                        )
                    length = resp.headers.get("Content-Length")
                    if length and length.isdigit():
                        total = int(length)
                    with part_path.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                            fh.write(chunk)
                            received += len(chunk)
                            yield {
                                "file": local_name, "received": received,
                                "total": total, "done": False,
                                "skipped": False, "error": None,
                            }
            except Exception as exc:
                part_path.unlink(missing_ok=True)
                yield {
                    "file": local_name, "received": received, "total": total,
                    "done": False, "skipped": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                return

            if total is not None and received != total:
                part_path.unlink(missing_ok=True)
                yield {
                    "file": local_name, "received": received, "total": total,
                    "done": False, "skipped": False,
                    "error": f"下载不完整: {received}/{total} 字节",
                }
                return

            part_path.replace(final_path)
            yield {
                "file": local_name, "received": received, "total": total,
                "done": True, "skipped": False, "error": None,
            }


async def download_all(
    dest_dir: Path, *, mirror: bool = False
) -> AsyncIterator[dict[str, Any]]:
    """Download text and vision roles in sequence."""
    for role in ("text", "vision"):
        async for event in download_model(role, dest_dir, mirror=mirror):
            yield {**event, "role": role}
