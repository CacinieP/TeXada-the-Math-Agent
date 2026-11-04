"""Linux package smoke boundaries without installing software or starting a GUI."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from texada.api import create_app
from texada.config import TeXadaConfig

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "linux_installed_smoke", ROOT / "scripts/smoke-installed-linux.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_smoke_environment_keeps_home_and_isolates_provider_and_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("TEXADA_API_BASE", "https://private.example")
    monkeypatch.setenv("TEXADA_DISABLE_BUNDLED_BACKEND", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-pass")
    monkeypatch.setenv("DISPLAY", ":99")
    before_home = smoke.os.environ.get("HOME")
    env = smoke.isolated_environment(tmp_path, 15555)
    assert env.get("HOME") == before_home
    assert env["DISPLAY"] == ":99"
    assert env["TEXADA_DATA_DIR"] == str(tmp_path / "data")
    assert env["TEXADA_API_PORT"] == "15555"
    assert env["TEXADA_BACKEND"] == "llama_server"
    assert "TEXADA_API_BASE" not in env
    assert "TEXADA_DISABLE_BUNDLED_BACKEND" not in env
    assert "OPENAI_API_KEY" not in env


def test_source_commit_must_match_the_checkout(monkeypatch):
    monkeypatch.setattr(smoke.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    assert smoke.verify_source("a" * 40) == "a" * 40
    with pytest.raises(RuntimeError, match="does not match"):
        smoke.verify_source("b" * 40)
    with pytest.raises(ValueError, match="full lowercase"):
        smoke.verify_source("abc123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper", [None, "committed", "review", "version", "parser", "runtime", "render", "tokens"]
)
async def test_packaged_contract_accepts_actual_api_and_rejects_tampering(tmp_path, tamper):
    runtime = tmp_path / "bundled/llama-server"
    app = create_app(
        TeXadaConfig(
            data_dir=tmp_path / "data", backend="llama_server", llama_server_binary=str(runtime)
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = (
            await client.post("/api/agent", json={"text": "二重积分", "render_mode": "katex"})
        ).json()
        runtime_response = (await client.get("/api/runtime")).json()
        settings = (await client.get("/api/settings/backend")).json()
    status = {"backend": "llama_server"}
    if tamper == "committed":
        result["committed"] = False
    elif tamper == "review":
        result["review"] = {"status": "pending"}
    elif tamper == "version":
        runtime_response["version"] = "0.4.1"
    elif tamper == "parser":
        result["semantic_document"]["parser_backend"] = "katex-0.17.0-v8"
    elif tamper == "runtime":
        settings["llama_server_binary"] = "/another/llama-server"
    elif tamper == "render":
        result["katex_html"] = '<span class="katex-fallback">x</span>'
    elif tamper == "tokens":
        result["tokens_used"] = True
    if tamper:
        with pytest.raises(RuntimeError):
            smoke.verify_result(status, runtime_response, settings, result, "0.4.2", runtime)
    else:
        smoke.verify_result(status, runtime_response, settings, result, "0.4.2", runtime)


def test_deb_rejects_wrong_release_before_any_install(monkeypatch, tmp_path):
    values = {"Package": "texada-shell", "Version": "0.4.1", "Architecture": "amd64"}
    monkeypatch.setattr(smoke.subprocess, "check_output", lambda args, **kwargs: values[args[-1]])
    install = Mock()
    monkeypatch.setattr(smoke.subprocess, "run", install)
    with pytest.raises(RuntimeError, match="Unexpected deb identity"):
        smoke.install_deb(tmp_path / "test.deb", "0.4.2")
    install.assert_not_called()


def test_appimage_extracts_and_runs_actual_packaged_apprun(monkeypatch, tmp_path):
    installer = tmp_path / "TeXada_0.4.2_amd64.AppImage"
    installer.write_bytes(b"ELF package")
    root = tmp_path / "isolated"
    root.mkdir()
    commands = []

    def extract(command, **kwargs):
        commands.append(command)
        bundle = root / "squashfs-root"
        bundle.mkdir()
        (bundle / "AppRun").write_text("#!/bin/sh\nexit 0\n")
        (bundle / "AppRun").chmod(0o700)
        runtime = bundle / "usr/lib/texada/resources/llama-server"
        runtime.mkdir(parents=True)
        (runtime / "llama-server").write_bytes(b"runtime")

    monkeypatch.setattr(smoke.subprocess, "run", extract)
    executable, runtime, mode = smoke.extract_appimage(installer, root)
    assert commands == [[str(root / "installer.AppImage"), "--appimage-extract"]]
    assert executable == root / "squashfs-root/AppRun"
    assert runtime.is_file()
    assert "AppRun launched" in mode
    assert installer.read_bytes() == b"ELF package"


def test_success_report_is_bound_to_artifact_and_missing_proof_cannot_write_it(
    monkeypatch, tmp_path
):
    installer = tmp_path / "TeXada_0.4.2_amd64.deb"
    installer.write_bytes(b"release artifact")
    output = tmp_path / "report.json"
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    monkeypatch.setattr(smoke.platform, "machine", lambda: "x86_64")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(smoke, "verify_source", lambda value: value)
    monkeypatch.setattr(
        smoke,
        "install_deb",
        lambda *args: (tmp_path / "desktop", tmp_path / "llama-server", "test installation"),
    )
    exercise = Mock(side_effect=RuntimeError("package failed"))
    monkeypatch.setattr(smoke, "exercise_desktop", exercise)
    args = [
        "--installer",
        str(installer),
        "--format",
        "deb",
        "--version",
        "0.4.2",
        "--expected-commit",
        "a" * 40,
        "--out",
        str(output),
    ]
    with pytest.raises(RuntimeError, match="package failed"):
        smoke.main(args)
    assert not output.exists()
    exercise.side_effect = None
    smoke.main(args)
    report = json.loads(output.read_text())
    assert report["installer_sha256"] == smoke.file_sha256(installer)
    assert report["source_commit"] == "a" * 40
    assert report["format"] == "deb"
    assert report["target"] == "x86_64-unknown-linux-gnu"
    assert report["version"] == "0.4.2"
    assert report["installed_desktop_started"] is True
    assert report["model_inference_tested"] is False
