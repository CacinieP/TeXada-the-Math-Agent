"""Packaging boundaries without signing, installing or contacting a real service."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def script_module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_sidecar_rejects_cross_target_before_replacing_existing_output(tmp_path, monkeypatch):
    build = script_module("build-backend-sidecar.py")
    monkeypatch.setattr(build, "host_triple", lambda: "aarch64-apple-darwin")
    monkeypatch.setattr(build, "BIN_DIR", tmp_path / "binaries")
    build.BIN_DIR.mkdir()
    existing = build.sidecar_path("x86_64-apple-darwin")
    existing.write_text("previous native output")
    with pytest.raises(ValueError, match="native target"):
        build.build_pyinstaller("x86_64-apple-darwin")
    assert existing.read_text() == "previous native output"


def test_signed_sidecar_requires_runtime_entitlements_and_secure_timestamp(monkeypatch, tmp_path):
    build = script_module("build-backend-sidecar.py")
    commands = []
    monkeypatch.setattr(build.subprocess, "run", lambda command, **kwargs: commands.append(
        (command, kwargs)))
    build.codesign_macos_item(tmp_path / "backend", "Developer ID Application: Synthetic",
                             entitlements=build.MACOS_SIDECAR_ENTITLEMENTS)
    command, options = commands[0]
    assert command[:4] == ["codesign", "--force", "--options", "runtime"]
    assert "--timestamp" in command
    assert command[command.index("--entitlements") + 1].endswith("macos-sidecar-entitlements.plist")
    assert options["check"] is True


def test_windows_smoke_starts_the_desktop_not_the_sidecar(tmp_path):
    smoke = script_module("smoke-installed-desktop.py")
    for name in ("texada-backend.exe", "uninstall.exe", "TeXada.exe"):
        (tmp_path / name).write_bytes(b"fixture")
    assert smoke.windows_desktop(tmp_path).name == "TeXada.exe"
    (tmp_path / "another.exe").write_bytes(b"fixture")
    with pytest.raises(RuntimeError, match="exactly one"):
        smoke.windows_desktop(tmp_path)


@pytest.mark.parametrize("failed_gate", [None, "codesign", "spctl", "missing_app"])
def test_macos_smoke_mounts_the_installer_and_enforces_inner_signature(
    tmp_path, monkeypatch, failed_gate,
):
    smoke = script_module("smoke-installed-desktop.py")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        if command[:2] == ["hdiutil", "attach"] and failed_gate != "missing_app":
            (Path(command[command.index("-mountpoint") + 1]) / "TeXada.app").mkdir()
        if command[0] == "ditto":
            shutil.copytree(command[1], command[2])
        if command[0] == failed_gate:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(smoke.subprocess, "run", run)
    if failed_gate:
        with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
            smoke.install_macos(tmp_path / "TeXada.dmg", tmp_path)
    else:
        assert smoke.install_macos(tmp_path / "TeXada.dmg", tmp_path) == tmp_path / "TeXada.app"
        assert any(command[:4] == ["codesign", "--verify", "--deep", "--strict"]
                   for command in commands)
        assert any(command[0] == "spctl" for command in commands)
    assert any(command[:2] == ["hdiutil", "attach"] for command in commands)
    assert any(command[:2] == ["hdiutil", "detach"] for command in commands)


@pytest.mark.parametrize("field", [
    None, "version", "committed", "parser_backend",
    "runtime_alias", "runtime_wrong", "windows_device",
])
def test_installed_contract_rejects_wrong_version_or_backend_result(tmp_path, field):
    smoke = script_module("smoke-installed-desktop.py")
    bundled = tmp_path / "llama-server"
    bundled.write_bytes(b"bundled runtime fixture")
    status = {"backend": "llama_server"}
    runtime = {"version": "0.4.2"}
    settings = {"llama_server_binary": str(bundled)}
    result = {"valid": True, "tokens_used": 0, "stop_reason": "deterministic_candidate",
              "committed": True, "review": None,
              "semantic_document": {"parser_backend": "katex-0.18.2-v8"},
              "katex_html": '<span class="katex">synthetic</span>'}
    if field == "version":
        runtime["version"] = "0.4.2-rc.3"
    elif field == "committed":
        result["committed"] = False
    elif field == "parser_backend":
        result["semantic_document"]["parser_backend"] = "wrong"
    elif field == "runtime_alias":
        alias = tmp_path / "same-runtime"
        alias.hardlink_to(bundled)
        settings["llama_server_binary"] = str(alias)
    elif field == "runtime_wrong":
        other = tmp_path / "other-runtime"
        other.write_bytes(b"different runtime fixture")
        settings["llama_server_binary"] = str(other)
    elif field == "windows_device":
        if os.name != "nt":
            pytest.skip("Win32 extended-length paths require a native Windows filesystem")
        settings["llama_server_binary"] = "\\\\?\\" + str(bundled.resolve())
    if field in {"version", "committed", "parser_backend", "runtime_wrong"}:
        with pytest.raises(AssertionError):
            smoke.validate_contract(status, runtime, settings, result, "0.4.2", bundled)
    else:
        smoke.validate_contract(status, runtime, settings, result, "0.4.2", bundled)


@pytest.mark.asyncio
async def test_installed_smoke_uses_actual_runtime_version_and_settings_contract(tmp_path):
    import httpx

    from texada.api import create_app
    from texada.config import TeXadaConfig

    smoke = script_module("smoke-installed-desktop.py")
    bundled = tmp_path / "llama-server"
    bundled.write_bytes(b"bundled runtime fixture")
    app = create_app(TeXadaConfig(data_dir=tmp_path, backend="llama_server",
                                 llama_server_binary=str(bundled)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as api:
        status = (await api.get("/api/status")).json()
        runtime = (await api.get("/api/runtime")).json()
        settings = (await api.get("/api/settings/backend")).json()
        result = (await api.post("/api/agent", json={"text": "二重积分"})).json()
    smoke.validate_contract(status, runtime, settings, result, "0.4.2", bundled)
