"""LlamaServerManager tests — fake binary, no real model or GPU needed.

The fake llama-server honors --version (prints a build line) and, for any
other invocation, serves a minimal OpenAI-compatible /v1/models endpoint.
"""
from __future__ import annotations

import socket
import stat
import textwrap

import pytest

from texada.config import TeXadaConfig
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
      echo "version: 0.4.1-dev (build 11046, commit deadbeef)"
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
            body = json.dumps({"data": [{"id": "text"}, {"id": "vision"}]}).encode()
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

OLD_BUILD_SERVER = FAKE_SERVER.replace("build 11046", f"build {MIN_BUILD - 1}")


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
def models(tmp_path):
    d = tmp_path / "models"
    d.mkdir()
    for name in (TEXT_MODEL_FILE, VISION_MODEL_FILE, VISION_MMPROJ_FILE):
        (d / name).write_text("fake", encoding="utf-8")
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


async def test_start_writes_preset_with_mmproj(config, models):
    manager = LlamaServerManager(config)
    await manager.start()
    preset = config.data_dir / "models" / "texada-models.ini"
    content = preset.read_text(encoding="utf-8")
    assert "[text]" in content
    assert "[vision]" in content
    assert "mmproj" in content
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


async def test_minicpm_model_sends_reasoning_effort_on_llama_server(tmp_path):
    from texada.core.model import MiniCPMModel

    config = TeXadaConfig(data_dir=tmp_path, backend="llama_server")
    model = MiniCPMModel(config)
    assert model._text_request_options() == {
        "extra_body": {"reasoning_effort": "none"}
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
