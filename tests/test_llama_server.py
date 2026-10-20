"""LlamaServerManager tests — fake binary, no real model or GPU needed.

The fake llama-server honors --version (prints a build line) and, for any
other invocation, serves a minimal OpenAI-compatible /v1/models endpoint.
"""
from __future__ import annotations

import hashlib
import socket
import stat
import textwrap

import pytest

from texada.config import TeXadaConfig
from texada.core import llama_server
from texada.core.llama_server import (
    MIN_BUILD,
    TEXT_MODEL_FILE,
    VISION_MMPROJ_FILE,
    VISION_MODEL_FILE,
    LlamaServerError,
    LlamaServerManager,
)

FAKE_SERVER = textwrap.dedent(
    """\
    #!/bin/sh
    if [ "$1" = "--version" ]; then
      echo "version: 0.4.1-dev (build 11609, commit deadbeef)"
      exit 0
    fi
    PORT=8080
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "--port" ]; then PORT="$arg"; fi
      prev="$arg"
    done
    python3 - "$PORT" <<'PY'
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[1])
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": "MiniCPM-V-4.7-1B"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    HTTPServer(("127.0.0.1", port), H).serve_forever()
    PY
    """
)

OLD_BUILD_SERVER = FAKE_SERVER.replace("build 11609", f"build {MIN_BUILD - 1}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_binary(tmp_path):
    path = tmp_path / "llama-server"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def config(tmp_path, fake_binary):
    port = _free_port()
    return TeXadaConfig(
        data_dir=tmp_path,
        llama_server_binary=str(fake_binary),
        llama_server_host=f"http://127.0.0.1:{port}",
    )


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "models"
    d.mkdir()
    pins = {}
    for name in (TEXT_MODEL_FILE, VISION_MODEL_FILE, VISION_MMPROJ_FILE):
        (d / name).write_text("fake", encoding="utf-8")
        pins[name] = hashlib.sha256(b"fake").hexdigest()
    # The start-time integrity check verifies the pinned digests; point the
    # pins at this fake content so the fixtures model correctly pinned files.
    monkeypatch.setattr(llama_server, "PINNED_SHA256", pins)
    return d


def test_resolve_binary_prefers_explicit_config(tmp_path):
    explicit = tmp_path / "custom-llama"
    explicit.write_text("#!/bin/sh\n", encoding="utf-8")
    explicit.chmod(0o755)
    config = TeXadaConfig(data_dir=tmp_path, llama_server_binary=str(explicit))
    assert LlamaServerManager(config).resolve_binary() == explicit


def test_resolve_binary_rejects_non_executable(tmp_path):
    broken = tmp_path / "broken"
    broken.write_text("x", encoding="utf-8")
    config = TeXadaConfig(data_dir=tmp_path, llama_server_binary=str(broken))
    with pytest.raises(LlamaServerError, match="不可执行"):
        LlamaServerManager(config).resolve_binary()


async def test_start_serves_and_stop_terminates(config, models):
    manager = LlamaServerManager(config)
    assert await manager.start() is True
    assert manager.is_running()
    assert await manager.stop() is True
    assert not manager.is_running()


async def test_start_uses_one_checkpoint_and_projector_for_both_roles(config, models):
    manager = LlamaServerManager(config)
    command = manager._build_command()
    assert "--models-preset" not in command
    assert command[command.index("--alias") + 1] == "MiniCPM-V-4.7-1B"
    assert command[command.index("-m") + 1] == str(manager.text_model_path)
    assert command[command.index("--mmproj") + 1] == str(manager.vision_model_paths[1])
    assert manager.text_model_path == manager.vision_model_paths[0]
    assert command[command.index("--reasoning") + 1] == "off"
    await manager.start()
    await manager.stop()


async def test_ensure_ready_starts_when_not_running(config, models):
    manager = LlamaServerManager(config)
    assert await manager.ensure_ready() is True
    await manager.stop()


async def test_missing_binary_gives_actionable_error(tmp_path, models):
    config = TeXadaConfig(
        data_dir=tmp_path,
        llama_server_binary=str(tmp_path / "does-not-exist"),
    )
    status = LlamaServerManager(config).get_status()
    assert status["status"] == "missing_binary"
    assert status["binary"] is None


async def test_old_build_is_refused(tmp_path, models):
    old = tmp_path / "llama-server-old"
    old.write_text(OLD_BUILD_SERVER, encoding="utf-8")
    old.chmod(0o755)
    port = _free_port()
    config = TeXadaConfig(
        data_dir=tmp_path,
        llama_server_binary=str(old),
        llama_server_host=f"http://127.0.0.1:{port}",
    )
    manager = LlamaServerManager(config)
    with pytest.raises(LlamaServerError, match="过旧"):
        await manager.start()


async def test_vision_ready_requires_both_vision_files(tmp_path, config, models):
    manager = LlamaServerManager(config)
    assert await manager.ensure_vision_ready() is True
    await manager.stop()

    (models / VISION_MMPROJ_FILE).unlink()
    with pytest.raises(LlamaServerError, match="视觉模型文件缺失"):
        await manager.ensure_vision_ready()


async def test_status_reports_missing_and_present_models(config, tmp_path):
    manager = LlamaServerManager(config)
    status = manager.get_status()
    assert status["status"] == "stopped"
    assert status["missing_models"] == [
        TEXT_MODEL_FILE,
        VISION_MODEL_FILE,
        VISION_MMPROJ_FILE,
    ]

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / TEXT_MODEL_FILE).write_text("fake", encoding="utf-8")
    (models_dir / VISION_MODEL_FILE).write_text("fake", encoding="utf-8")
    status = manager.get_status()
    assert status["missing_models"] == [VISION_MMPROJ_FILE]
    assert status["text_model_installed"] is True
    assert status["vision_model_installed"] is False


async def test_minicpm_v47_disables_thinking_on_llama_server(tmp_path):
    from texada.core.model import MiniCPMModel

    config = TeXadaConfig(data_dir=tmp_path, backend="llama_server")
    model = MiniCPMModel(config)
    assert model._text_request_options() == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
    }


async def test_minicpm_model_keeps_ollama_behavior(tmp_path):
    from texada.core.model import MiniCPMModel

    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        model_name="hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M",
    )
    model = MiniCPMModel(config)
    assert model._text_request_options() == {
        "extra_body": {"reasoning_effort": "none"}
    }

    config = TeXadaConfig(
        data_dir=tmp_path, backend="ollama", model_name="some-other-model"
    )
    assert MiniCPMModel(config)._text_request_options() == {}


def _stale_models(tmp_path, monkeypatch):
    """Model files present at the expected paths but not matching the pins."""
    models = tmp_path / "models"
    models.mkdir()
    (models / TEXT_MODEL_FILE).write_bytes(b"stale weights")
    (models / VISION_MMPROJ_FILE).write_bytes(b"stale projector")
    monkeypatch.setattr(llama_server, "PINNED_SHA256", {
        TEXT_MODEL_FILE: hashlib.sha256(b"fresh weights").hexdigest(),
        VISION_MMPROJ_FILE: hashlib.sha256(b"fresh projector").hexdigest(),
    })
    return models


async def test_start_refuses_a_mismatched_pinned_model(tmp_path, monkeypatch, config):
    _stale_models(tmp_path, monkeypatch)
    manager = LlamaServerManager(config)
    with pytest.raises(LlamaServerError, match="校验和不匹配"):
        manager._build_command()


async def test_missing_models_are_reported_before_hash_mismatch(
    tmp_path, monkeypatch, config
):
    models = _stale_models(tmp_path, monkeypatch)
    (models / VISION_MMPROJ_FILE).unlink()
    manager = LlamaServerManager(config)
    with pytest.raises(LlamaServerError, match="模型文件缺失"):
        manager._build_command()


async def test_status_reports_pinned_hash_mismatch(tmp_path, monkeypatch, config):
    _stale_models(tmp_path, monkeypatch)
    manager = LlamaServerManager(config)
    status = await manager.aget_status()
    assert status["status"] == "model_hash_mismatch"
    assert status["ready"] is False
    assert status["pinned_hash_mismatch"] == [TEXT_MODEL_FILE, VISION_MMPROJ_FILE]
    assert "重新下载" in status["next_action"]


def test_digest_verification_is_cached_per_file(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    (models / TEXT_MODEL_FILE).write_bytes(b"weights")
    (models / VISION_MMPROJ_FILE).write_bytes(b"projector")
    monkeypatch.setattr(llama_server, "PINNED_SHA256", {
        TEXT_MODEL_FILE: hashlib.sha256(b"other weights").hexdigest(),
        VISION_MMPROJ_FILE: hashlib.sha256(b"other projector").hexdigest(),
    })
    hashed: list[str] = []
    real = llama_server.sha256_file

    def counting(path):
        hashed.append(path.name)
        return real(path)

    monkeypatch.setattr(llama_server, "sha256_file", counting)
    manager = LlamaServerManager(TeXadaConfig(data_dir=tmp_path))
    expected = [TEXT_MODEL_FILE, VISION_MMPROJ_FILE]
    assert manager._mismatched_pinned_models() == expected
    assert manager._mismatched_pinned_models() == expected
    assert sorted(hashed) == sorted(expected)
