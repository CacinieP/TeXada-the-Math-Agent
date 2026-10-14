"""Install a freshly built package in a temporary location and exercise its bundled backend."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base: str, path: str, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    installer = args.installer.resolve()
    with tempfile.TemporaryDirectory(prefix="texada-installed-smoke-") as directory:
        root = Path(directory)
        app = None
        if sys.platform == "darwin":
            mount = root / "mounted"
            mount.mkdir()
            subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(installer),
                    "-mountpoint",
                    str(mount),
                    "-nobrowse",
                    "-readonly",
                    "-quiet",
                ],
                check=True,
            )
            try:
                source = next(mount.glob("*.app"))
                app = root / source.name
                subprocess.run(["ditto", str(source), str(app)], check=True)
            finally:
                subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=True)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            executable = app / "Contents/MacOS" / info["CFBundleExecutable"]
            runtime = next(app.rglob("llama-server"))
        elif sys.platform == "win32":
            install_dir = root / "installed"
            subprocess.run([str(installer), "/S", f"/D={install_dir}"], check=True, timeout=120)
            executable = next(
                p for p in install_dir.glob("*.exe") if "uninstall" not in p.name.lower()
            )
            runtime = next(install_dir.rglob("llama-server.exe"))
        else:
            raise RuntimeError("Native installer smoke only supports macOS and Windows")
        version = subprocess.run(
            [str(runtime), "--version"], check=True, text=True, capture_output=True, timeout=30
        )
        assert "build 11609" in version.stdout + version.stderr
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(
            os.environ,
            TEXADA_API_PORT=str(port),
            TEXADA_DATA_DIR=str(root / "data"),
            TEXADA_BACKEND="llama_server",
        )
        with (root / "desktop.log").open("w") as log:
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
                            "Installed desktop exited: " + (root / "desktop.log").read_text()
                        )
                    try:
                        status = request(base, "/api/status")
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Installed backend unavailable: "
                                + (root / "desktop.log").read_text()
                            ) from None
                        time.sleep(0.5)
                assert status["backend"] == "llama_server", status
                result = request(base, "/api/agent", {"text": "二重积分", "render_mode": "katex"})
                assert result["valid"] and result["tokens_used"] == 0, result
                assert result["semantic_document"]["parser_backend"] == "katex-0.17.0-v8", result
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        {
                            "platform": sys.platform,
                            "installer": installer.name,
                            "installed_desktop_started": True,
                            "bundled_backend_started": True,
                            "bundled_runtime_build": 11609,
                            "status": status,
                            "deterministic_compile_and_render_valid": True,
                            "model_inference_tested": False,
                            "scope": (
                                "Native clean installation and launch; "
                                "no weights bundled or downloaded"
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
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
