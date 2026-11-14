#!/usr/bin/env python3
"""Install/extract Linux release artifacts and exercise the packaged desktop.

Run on native Linux x64 under a graphical display (CI uses xvfb-run). A deb is
installed with apt; an AppImage is extracted and its AppRun is launched. No
model weights are downloaded and no inference-readiness claim is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "x86_64-unknown-linux-gnu"
KATEX_BACKEND = "katex-0.18.2-v8"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source(expected: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", expected):
        raise ValueError("--expected-commit must be the full lowercase commit SHA")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if current != expected:
        raise RuntimeError("Smoke checkout does not match --expected-commit")
    return current


def only_file(paths, description: str) -> Path:
    candidates = [path for path in paths if path.is_file()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one {description}; found {len(candidates)}")
    return candidates[0]


def install_deb(installer: Path, version: str) -> tuple[Path, Path, str]:
    def field(name):
        return subprocess.check_output(
            ["dpkg-deb", "--field", str(installer), name], text=True
        ).strip()

    package, package_version, architecture = (
        field("Package"),
        field("Version"),
        field("Architecture"),
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", package):
        raise RuntimeError("Invalid Debian package name")
    if package_version != version or architecture != "amd64":
        raise RuntimeError(
            f"Unexpected deb identity: version={package_version}, architecture={architecture}"
        )
    privilege = [] if os.geteuid() == 0 else ["sudo", "-n"]
    subprocess.run(
        [
            *privilege,
            "apt-get",
            "install",
            "--yes",
            "--reinstall",
            "--no-install-recommends",
            str(installer),
        ],
        check=True,
        timeout=240,
    )
    installed_version = subprocess.check_output(
        ["dpkg-query", "--show", "--showformat=${Version}", package],
        text=True,
    ).strip()
    if installed_version != version:
        raise RuntimeError("Installed Debian package version does not match this release")
    files = [
        Path(value)
        for value in subprocess.check_output(
            ["dpkg-query", "--listfiles", package],
            text=True,
        ).splitlines()
    ]
    desktop = only_file(
        (path for path in files if path.suffix == ".desktop"), "installed desktop entry"
    )
    contents = desktop.read_text(encoding="utf-8")
    match = re.search(r"^Exec=(?:\"([^\"]+)\"|([^\s]+))", contents, re.MULTILINE)
    if not match:
        raise RuntimeError("Installed desktop entry has no executable")
    command = Path(match.group(1) or match.group(2))
    executable = only_file(
        (path for path in files if path.name == command.name and path.parent.name == "bin"),
        "installed desktop executable",
    )
    runtime = only_file(
        (path for path in files if path.name == "llama-server"), "bundled llama-server"
    )
    return executable, runtime, "deb installed with apt; launch packaged desktop entry executable"


def extract_appimage(installer: Path, root: Path) -> tuple[Path, Path, str]:
    # Artifact downloads can lose executable mode. Change only a temporary copy.
    copied = root / "installer.AppImage"
    shutil.copyfile(installer, copied)
    copied.chmod(0o700)
    subprocess.run(
        [str(copied), "--appimage-extract"],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=120,
    )
    bundle = root / "squashfs-root"
    executable = bundle / "AppRun"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("Extracted AppImage has no executable AppRun")
    runtime = only_file(bundle.rglob("llama-server"), "AppImage bundled llama-server")
    return executable, runtime, "AppImage extracted and packaged AppRun launched without FUSE"


def isolated_environment(root: Path, port: int) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("TEXADA_")
        and "API_KEY" not in name.upper()
        and not name.upper().endswith(("_TOKEN", "_SECRET"))
    }
    # HOME remains unchanged. The application and WebKit use isolated data paths.
    env.update(
        TEXADA_API_HOST="127.0.0.1",
        TEXADA_API_PORT=str(port),
        TEXADA_DATA_DIR=str(root / "data"),
        TEXADA_BACKEND="llama_server",
        XDG_CONFIG_HOME=str(root / "xdg-config"),
        XDG_DATA_HOME=str(root / "xdg-data"),
        XDG_CACHE_HOME=str(root / "xdg-cache"),
        LC_ALL="C.UTF-8",
        GDK_BACKEND="x11",
        LIBGL_ALWAYS_SOFTWARE="1",
        NO_PROXY="127.0.0.1,localhost,::1",
    )
    return env


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base: str, path: str, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base + path, data=payload, headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as response:
        return json.load(response)


def verify_result(
    status: dict, runtime: dict, settings: dict, result: dict, version: str, bundled_runtime: Path
) -> None:
    if status.get("backend") != "llama_server":
        raise RuntimeError("Packaged backend did not use the isolated built-in profile")
    if runtime.get("version") != version:
        raise RuntimeError("Packaged API version does not match release version")
    configured_runtime = settings.get("llama_server_binary")
    if (
        not isinstance(configured_runtime, str)
        or Path(configured_runtime).resolve() != bundled_runtime.resolve()
    ):
        raise RuntimeError("Desktop did not pass its bundled llama-server path to the backend")
    valid = (
        result.get("valid") is True
        and type(result.get("tokens_used")) is int
        and result["tokens_used"] == 0
        and result.get("stop_reason") == "deterministic_candidate"
        and result.get("committed") is True
        and "review" in result
        and result["review"] is None
        and isinstance(result.get("semantic_document"), dict)
        and result["semantic_document"].get("parser_backend") == KATEX_BACKEND
        and isinstance(result.get("katex_html"), str)
        and 'class="katex"' in result["katex_html"]
        and "katex-fallback" not in result["katex_html"]
    )
    if not valid:
        raise RuntimeError("Packaged deterministic formula, KaTeX or direct-commit contract failed")


def stop_process_group(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)


def verify_english_first_window(proc, screenshot: Path) -> None:
    """Wait for the actual X11 window to render its English navigation."""
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    expected = {"complete", "presets", "history", "settings"}
    deadline = time.monotonic() + 25
    detected = set()
    while time.monotonic() < deadline and proc.poll() is None:
        window = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--limit", "1", "--name", "^TeXada$"],
            text=True, capture_output=True, timeout=5,
        )
        if window.returncode == 0 and window.stdout.strip().isdigit():
            capture = subprocess.run(
                ["import", "-window", window.stdout.strip(), str(screenshot)],
                capture_output=True, timeout=5,
            )
            if capture.returncode == 0:
                ocr = subprocess.run(
                    ["tesseract", str(screenshot), "stdout", "-l", "eng", "--psm", "11"],
                    check=True, text=True, capture_output=True, timeout=10,
                )
                detected = expected.intersection(re.findall(r"[a-z]+", ocr.stdout.lower()))
                if len(detected) >= 3:
                    return
        time.sleep(0.5)
    raise RuntimeError(f"English navigation not visible in TeXada window: {sorted(detected)}")


def exercise_desktop(
    executable: Path, bundled_runtime: Path, root: Path, version: str, *,
    appimage: bool, screenshot: Path,
) -> None:
    runtime_check = subprocess.run(
        [str(bundled_runtime), "--version"], check=True, text=True, capture_output=True, timeout=30
    )
    if not re.search(r"\bbuild\s+11669\b", runtime_check.stdout + runtime_check.stderr):
        raise RuntimeError("Bundled llama-server is not the pinned build 11669")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = isolated_environment(root, port)
    if appimage:
        env.update(APPDIR=str(executable.parent), APPIMAGE=str(root / "installer.AppImage"))
    log_path = root / "desktop.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(executable)],
            env=env,
            stdout=log,
            stderr=log,
            cwd=executable.parent,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 90
            while True:
                if proc.poll() is not None:
                    raise RuntimeError("Installed Linux desktop exited before API readiness")
                try:
                    status = request(base, "/api/status")
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Packaged Linux desktop backend did not become available"
                        ) from None
                    time.sleep(0.5)
            runtime = request(base, "/api/runtime")
            settings = request(base, "/api/settings/backend")
            ui_settings = request(base, "/api/settings/ui")
            if (
                ui_settings.get("ui_language") != "en"
                or ui_settings.get("ui_language_explicit") is not False
            ):
                raise RuntimeError("Fresh Linux UI must default to English under C.UTF-8")
            result = request(base, "/api/agent", {"text": "二重积分", "render_mode": "katex"})
            verify_result(status, runtime, settings, result, version, bundled_runtime)
            verify_english_first_window(proc, screenshot)
        except Exception:
            sys.stderr.write(log_path.read_text(encoding="utf-8", errors="replace")[-8000:])
            raise
        finally:
            stop_process_group(proc)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--format", choices=("deb", "AppImage", "appimage"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("Installed Linux smoke requires native Linux x64")
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("A graphical display is required; use xvfb-run in CI")
    commit = verify_source(args.expected_commit)
    installer = args.installer.resolve(strict=True)
    installer_hash = file_sha256(installer)
    kind = args.format.lower()
    if (kind == "deb" and installer.suffix.lower() != ".deb") or (
        kind == "appimage" and installer.suffix.lower() != ".appimage"
    ):
        raise RuntimeError("Installer extension does not match --format")
    with tempfile.TemporaryDirectory(prefix="texada-linux-installed-") as directory:
        root = Path(directory).resolve()
        if kind == "deb":
            executable, runtime, installation = install_deb(installer, args.version)
        else:
            executable, runtime, installation = extract_appimage(installer, root)
        exercise_desktop(
            executable, runtime, root, args.version,
            appimage=kind == "appimage", screenshot=args.screenshot.resolve(),
        )
        report = {
            "platform": "linux",
            "target": TARGET,
            "format": kind,
            "source_commit": commit,
            "installer": installer.name,
            "installer_sha256": installer_hash,
            "version": args.version,
            "installation_mode": installation,
            "installed_desktop_started": True,
            "bundled_backend_started": True,
            "bundled_runtime_build": 11669,
            "deterministic_compile_and_render_valid": True,
            "candidate_commits_directly": True,
            "english_first_window_verified": True,
            "model_inference_tested": False,
            "scope": (
                "Native Linux x64 startup, English window OCR and deterministic rendering; "
                "no model download or inference"
            ),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
