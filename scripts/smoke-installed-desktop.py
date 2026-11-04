"""Install a freshly built package in a temporary location and exercise its bundled backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_macos(installer: Path, root: Path) -> Path:
    """Exercise the actual DMG, never a nearby build-directory app."""
    mount = root / "mounted"
    mount.mkdir()
    subprocess.run(
        ["hdiutil", "attach", str(installer), "-mountpoint", str(mount), "-nobrowse", "-readonly"],
        input="Y\n", text=True, check=True, timeout=90,
    )
    try:
        applications = list(mount.glob("*.app"))
        if len(applications) != 1:
            raise RuntimeError("DMG must contain exactly one installable app")
        source = applications[0]
        installed = root / source.name
        subprocess.run(["ditto", str(source), str(installed)], check=True, timeout=90)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=True, timeout=30)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(installed)], check=True)
    subprocess.run(
        ["spctl", "--assess", "--type", "execute", "--verbose", str(installed)], check=True
    )
    return installed


def windows_desktop(install_dir: Path) -> Path:
    candidates = [path for path in install_dir.glob("*.exe")
                  if "uninstall" not in path.name.lower()
                  and path.stem.lower() not in {"texada-backend", "llama-server"}]
    if len(candidates) != 1:
        raise RuntimeError("Installed package must contain exactly one desktop executable")
    return candidates[0]


def validate_contract(status, runtime, settings, result, version, bundled_runtime):
    assert status["backend"] == "llama_server", status
    assert runtime["version"] == version, runtime
    assert Path(settings["llama_server_binary"]).resolve() == bundled_runtime.resolve(), settings
    assert result["valid"] and result["tokens_used"] == 0, result
    assert result["stop_reason"] == "deterministic_candidate", result
    assert result["committed"] is True, result
    assert result["review"] is None, result
    assert result["semantic_document"]["parser_backend"] == "katex-0.18.2-v8", result
    assert 'class="katex"' in result["katex_html"], result
    assert "katex-fallback" not in result["katex_html"], result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base: str, path: str, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    installer = args.installer.resolve()
    if not installer.is_file():
        parser.error("Installer does not exist")
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != args.expected_commit:
        parser.error("Validation checkout does not match the requested release commit")
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64", "x86_64", "amd64"}:
        target = ("aarch64-apple-darwin" if machine in {"arm64", "aarch64"}
                  else "x86_64-apple-darwin")
        package_format = "dmg"
    elif sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        target, package_format = "x86_64-pc-windows-msvc", "nsis"
    else:
        parser.error("This smoke supports native macOS and Windows x64 only")
    installer_sha256 = file_sha256(installer)
    with tempfile.TemporaryDirectory(prefix="texada-installed-smoke-") as directory:
        root = Path(directory).resolve()
        app = None
        if sys.platform == "darwin":
            app = install_macos(installer, root)
            installation_mode = "DMG mounted and app copied to temporary installation"
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            assert info["CFBundleShortVersionString"] == args.version, info
            executable = app / "Contents/MacOS" / info["CFBundleExecutable"]
            runtime = next(p for p in app.rglob("llama-server") if p.is_file())
        elif sys.platform == "win32":
            install_dir = root / "installed"
            subprocess.run([str(installer), "/S", f"/D={install_dir}"], check=True, timeout=120)
            executable = windows_desktop(install_dir)
            runtime = next(p for p in install_dir.rglob("llama-server.exe") if p.is_file())
            installation_mode = "NSIS installer executed in temporary installation"
        else:
            raise RuntimeError("Native installer smoke only supports macOS and Windows")
        version = subprocess.run(
            [str(runtime), "--version"], check=True, text=True, capture_output=True, timeout=30
        )
        assert re.search(r"\bbuild\s+11669\b", version.stdout + version.stderr), version
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(
            {key: value for key, value in os.environ.items()
             if not key.startswith("TEXADA_") and "API_KEY" not in key.upper()
             and not key.upper().endswith(("_TOKEN", "_SECRET"))},
            TEXADA_API_PORT=str(port),
            TEXADA_DATA_DIR=str(root / "data"),
            TEXADA_BACKEND="llama_server",
        )
        with (root / "desktop.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(executable)],
                env=env,
                stdout=log,
                stderr=log,
                **({"start_new_session": True} if os.name != "nt" else {}),
            )
            try:
                deadline = time.monotonic() + 90
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(
                            "Installed desktop exited: "
                            + (root / "desktop.log").read_text(encoding="utf-8", errors="replace")
                        )
                    try:
                        status = request(base, "/api/status")
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Installed backend unavailable: "
                                + (root / "desktop.log").read_text(
                                    encoding="utf-8", errors="replace"
                                )
                            ) from None
                        time.sleep(0.5)
                result = request(base, "/api/agent", {"text": "二重积分", "render_mode": "katex"})
                runtime_info = request(base, "/api/runtime")
                settings = request(base, "/api/settings/backend")
                validate_contract(status, runtime_info, settings, result, args.version, runtime)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        {
                            "platform": sys.platform,
                            "target": target,
                            "format": package_format,
                            "version": args.version,
                            "source_commit": commit,
                            "installer": installer.name,
                            "installer_sha256": installer_sha256,
                            "signature_verified": sys.platform == "darwin",
                            "installation_mode": installation_mode,
                            "installed_desktop_started": True,
                            "bundled_backend_started": True,
                            "bundled_runtime_build": 11669,
                            "status": status,
                            "deterministic_compile_and_render_valid": True,
                            "candidate_commits_directly": True,
                            "model_inference_tested": False,
                            "scope": (
                                "Native clean installation and launch; "
                                "no weights bundled or downloaded"
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            finally:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)


if __name__ == "__main__":
    main()
