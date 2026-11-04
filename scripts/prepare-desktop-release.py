"""Fail closed unless release versions, installed checks and artifact bytes agree."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    ("aarch64-apple-darwin", "dmg"): ".dmg",
    ("x86_64-apple-darwin", "dmg"): ".dmg",
    ("x86_64-pc-windows-msvc", "nsis"): ".exe",
    ("x86_64-unknown-linux-gnu", "deb"): ".deb",
    ("x86_64-unknown-linux-gnu", "appimage"): ".appimage",
}
GATES = ("installed_desktop_started", "bundled_backend_started",
         "deterministic_compile_and_render_valid", "candidate_commits_directly")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def identity(commit: str, version: str | None = None) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "expected commit must be a full SHA")
    if version is not None:
        require(bool(re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version)),
                "invalid release version")


def read_toml(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text())


def preflight(expected: str, github_output: Path | None) -> dict:
    identity(expected)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == expected, "checkout does not match the expected source commit")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                    cwd=ROOT, text=True)
    require(not dirty.strip(), "release checkout has tracked changes")
    version = read_toml("pyproject.toml")["project"]["version"]
    identity(expected, version)
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/"):
        require(ref == f"refs/tags/v{version}", "release tag and source version disagree")
    package = json.loads((ROOT / "package.json").read_text())
    npm_lock = json.loads((ROOT / "package-lock.json").read_text())
    tauri = json.loads((ROOT / "tauri-shell/src-tauri/tauri.conf.json").read_text())
    cargo = read_toml("tauri-shell/src-tauri/Cargo.toml")
    cargo_lock = read_toml("tauri-shell/src-tauri/Cargo.lock")
    uv_lock = read_toml("uv.lock")
    versions = [package["version"], npm_lock["version"],
                npm_lock["packages"][""]["version"], tauri["version"], cargo["package"]["version"],
                next(p["version"] for p in cargo_lock["package"] if p["name"] == "texada-shell"),
                next(p["version"] for p in uv_lock["package"] if p["name"] == "texada")]
    require(all(value == version for value in versions), "release metadata versions disagree")
    init = ast.parse((ROOT / "src/texada/__init__.py").read_text())
    defaults = [n.value.value for n in ast.walk(init) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets)
                and isinstance(n.value, ast.Constant)]
    api = ast.parse((ROOT / "src/texada/api.py").read_text())
    app_version = next(n for n in api.body if isinstance(n, ast.FunctionDef)
                       and n.name == "_app_version")
    defaults += [n.value.value for n in ast.walk(app_version) if isinstance(n, ast.Return)
                 and isinstance(n.value, ast.Constant)]
    require(defaults == [version, version], "packaged Python version defaults disagree")
    require(f"v{version}" in (ROOT / "tauri-shell/src/index.html").read_text(),
            "frontend version does not match")
    require(f"## {version} - " in (ROOT / "CHANGELOG.md").read_text(),
            "changelog lacks the exact release section")
    result = {"version": version, "tag": f"v{version}", "source_commit": expected}
    if github_output:
        with github_output.open("a") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
    return result


def collect(source: Path, destination: Path, commit: str, version: str) -> dict:
    identity(commit, version)
    source = source.resolve(strict=True)
    destination = destination.resolve()
    require(not destination.exists(), "staged release output already exists")
    require(not destination.is_relative_to(source), "output must be outside the input tree")
    files: dict[str, Path] = {}
    for path in source.rglob("*"):
        require(not path.is_symlink(), "release artifacts must not contain symbolic links")
        if path.is_file():
            require(path.name not in files, "duplicate artifact basename: " + path.name)
            files[path.name] = path
    installers = {name: path for name, path in files.items()
                  if path.suffix.lower() in set(TARGETS.values())}
    require(len(installers) == len(TARGETS), "expected exactly five platform installers")
    smokes: dict[tuple[str, str], tuple[dict, Path]] = {}
    notarizations: dict[str, tuple[dict, Path]] = {}
    for path in files.values():
        if path.suffix.lower() != ".json":
            continue
        data = json.loads(path.read_text())
        require(isinstance(data, dict), "release evidence must be a JSON object")
        require(data.get("source_commit") == commit, "evidence belongs to another source commit")
        if "installed_desktop_started" in data:
            key = (data.get("target"), str(data.get("format", "")).lower())
            require(key in TARGETS and key not in smokes, "unknown or duplicate installed check")
            require(data.get("version") == version, "installed version differs from release")
            require(all(data.get(gate) is True for gate in GATES), "installed validation failed")
            require(data.get("bundled_runtime_build") == 11669, "unexpected bundled runtime")
            require(data.get("model_inference_tested") is False,
                    "engineering smoke must state its model-test scope")
            if key[1] == "dmg":
                require(data.get("signature_verified") is True, "macOS signature was not verified")
            smokes[key] = (data, path)
        else:
            target = data.get("target")
            require(target in {"aarch64-apple-darwin", "x86_64-apple-darwin"}
                    and target not in notarizations, "unknown or duplicate notarization record")
            require(data.get("status") == "Accepted"
                    and data.get("stapler_validated") is True
                    and data.get("gatekeeper_assessed") is True,
                    "macOS notarization/stapling/Gatekeeper validation failed")
            require(bool(data.get("submission_id")), "notarization submission identity missing")
            notarizations[target] = (data, path)
    require(set(smokes) == set(TARGETS), "installed validation is missing for a platform/format")
    require(len(notarizations) == 2, "both macOS notarization records are required")
    selected: dict[str, Path] = {}
    packages = []
    used = set()
    for key, suffix in TARGETS.items():
        data, evidence = smokes[key]
        name = data.get("installer")
        require(isinstance(name, str) and Path(name).name == name and name in installers,
                "installed evidence does not identify an attached installer basename")
        require(name not in used and name.lower().endswith(suffix),
                "installer does not match a unique platform/format")
        require(bool(re.search(r"(?:^|[_-])" + re.escape(version) + r"(?:[_-]|\.)", name)),
                "installer filename does not contain the release version")
        path = installers[name]
        digest = sha256(path)
        require(data.get("installer_sha256") == digest,
                "installer changed after installed validation")
        selected[name] = path
        selected[evidence.name] = evidence
        record = {"target": key[0], "format": key[1], "filename": name,
                  "bytes": path.stat().st_size, "sha256": digest,
                  "installed_validation": evidence.name,
                  "model_inference_tested": False}
        if key[1] == "dmg":
            notary, notary_file = notarizations[key[0]]
            require(notary.get("installer") == name and notary.get("installer_sha256") == digest,
                    "notarization record does not match the final installer bytes")
            record["notarization"] = notary_file.name
            record["code_signing"] = "Developer ID; notarized, stapled and Gatekeeper assessed"
            selected[notary_file.name] = notary_file
        else:
            record["code_signing"] = "not configured; verify the published SHA256"
        packages.append(record)
        used.add(name)
    require(used == set(installers), "an installer has no matching validation")
    manifest = {"schema_version": 1, "version": version, "source_commit": commit,
                "bundled_runtime_build": 11669, "installer_count": len(packages),
                "packages": packages,
                "validation_scope": "Native installation and deterministic API/KaTeX smoke; "
                "not model accuracy or independent human formula acceptance"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="texada-release-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "ready"
        staged.mkdir()
        for name, path in selected.items():
            shutil.copy2(path, staged / name)
        (staged / "release-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        checksums = "".join(f"{sha256(path)}  {path.name}\n"
                            for path in sorted(staged.iterdir()))
        (staged / "SHA256SUMS").write_text(checksums)
        staged.replace(destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--expected-commit", required=True)
    check.add_argument("--github-output", type=Path)
    stage = commands.add_parser("collect")
    stage.add_argument("--input", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    stage.add_argument("--expected-commit", required=True)
    stage.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        result = (preflight(args.expected_commit, args.github_output)
                  if args.command == "preflight"
                  else collect(args.input, args.output, args.expected_commit, args.version))
    except (ValueError, KeyError, StopIteration, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"Release validation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
