#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "tauri-shell" / "src-tauri" / "binaries"
RESOURCE_BACKEND_DIR = ROOT / "tauri-shell" / "src-tauri" / "resources" / "texada-backend"
ENTRYPOINT = ROOT / "src" / "texada" / "sidecar.py"
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}


def host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("Could not determine rust host triple from `rustc -vV`.")


def sidecar_path(target: str) -> Path:
    suffix = ".exe" if target.endswith("windows-msvc") or "windows" in target else ""
    return BIN_DIR / f"texada-backend-{target}{suffix}"


def is_macos_target(target: str) -> bool:
    return "apple-darwin" in target


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(4) in MACHO_MAGICS
    except OSError:
        return False


def make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def codesign_macos_item(path: Path, identity: str) -> None:
    cmd = ["codesign", "--force", "--options", "runtime", "--sign", identity]
    if identity != "-":
        cmd.append("--timestamp")
    cmd.append(str(path))
    subprocess.run(cmd, cwd=ROOT, check=True)


def codesign_macos_tree(path: Path) -> None:
    if sys.platform != "darwin":
        return
    identity = os.environ.get("PYINSTALLER_CODESIGN_IDENTITY", "-")
    frameworks = sorted(
        (candidate for candidate in path.rglob("*.framework") if candidate.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for candidate in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if (
            not candidate.is_file()
            or not is_macho(candidate)
            or any(part.endswith(".framework") for part in candidate.parts)
        ):
            continue
        codesign_macos_item(candidate, identity)
    for framework in frameworks:
        codesign_macos_item(framework, identity)


def build_stub(target: str) -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    RESOURCE_BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    (RESOURCE_BACKEND_DIR / ".keep").write_text(
        "generated cargo-check placeholder\n",
        encoding="utf-8",
    )
    output = sidecar_path(target)
    if output.suffix == ".exe":
        output.write_bytes(b"MZ\n")
    else:
        output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        make_executable(output)
    return output


def build_pyinstaller(target: str) -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    output = sidecar_path(target)
    if output.exists():
        output.unlink()
    shutil.rmtree(RESOURCE_BACKEND_DIR, ignore_errors=True)

    work_dir = ROOT / "build" / "pyinstaller"
    dist_dir = ROOT / "dist" / "pyinstaller"
    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(dist_dir, ignore_errors=True)

    cmd = [
        "uv",
        "run",
        "--managed-python",
        "--extra",
        "dev",
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--name",
        "texada-backend",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        str(ENTRYPOINT),
    ]
    if is_macos_target(target):
        cmd.extend(["--onedir", "--contents-directory", "_internal"])
    else:
        cmd.append("--onefile")
    if sys.platform == "darwin":
        cmd.extend([
            "--codesign-identity",
            os.environ.get("PYINSTALLER_CODESIGN_IDENTITY", "-"),
        ])
    subprocess.run(cmd, cwd=ROOT, check=True)

    if is_macos_target(target):
        built_dir = dist_dir / "texada-backend"
        built = built_dir / "texada-backend"
        if not built.exists():
            raise FileNotFoundError(f"PyInstaller did not create {built}")
        shutil.copytree(built_dir, RESOURCE_BACKEND_DIR)
        codesign_macos_tree(RESOURCE_BACKEND_DIR)
        output.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            'DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
            'for candidate in \\\n'
            '  "$DIR/../Resources/resources/texada-backend/texada-backend" \\\n'
            '  "$DIR/../Resources/texada-backend/texada-backend" \\\n'
            '  "$DIR/../resources/texada-backend/texada-backend"; do\n'
            '  if [ -x "$candidate" ]; then\n'
            '    exec "$candidate" "$@"\n'
            "  fi\n"
            "done\n"
            'echo "Could not find bundled texada-backend executable" >&2\n'
            "exit 127\n",
            encoding="utf-8",
        )
    else:
        built = dist_dir / ("texada-backend.exe" if output.suffix == ".exe" else "texada-backend")
        if not built.exists():
            raise FileNotFoundError(f"PyInstaller did not create {built}")
        shutil.move(str(built), output)
        RESOURCE_BACKEND_DIR.mkdir(parents=True, exist_ok=True)
        (RESOURCE_BACKEND_DIR / ".keep").write_text(
            "generated empty backend resource directory\n",
            encoding="utf-8",
        )
    make_executable(output)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or stub the bundled TeXada backend sidecar."
    )
    parser.add_argument(
        "--target",
        default="",
        help="Rust target triple. Defaults to `rustc -vV` host.",
    )
    parser.add_argument(
        "--mode",
        choices=("pyinstaller", "stub"),
        default="pyinstaller",
        help="`pyinstaller` creates the real release sidecar; `stub` is only for cargo check.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = args.target.strip() or host_triple()
    output = build_stub(target) if args.mode == "stub" else build_pyinstaller(target)
    print(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"backend sidecar build failed: {exc}", file=sys.stderr)
        raise
