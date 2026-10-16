"""Archive layout fixtures; no network or actual package integrity validation."""

import hashlib
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("target", "binary", "digest"),
    [
        (
            "aarch64-apple-darwin",
            "llama-server",
            "dbed55493d72bc1ba2babc8770d669c2289b5bc4ee9fb2a4dfc158d45b7d13fd",
        ),
        (
            "x86_64-apple-darwin",
            "llama-server",
            "cab28238d78158109b48deb27b05d50e0dcef56275d2e76da9ca8281526c7532",
        ),
        (
            "x86_64-pc-windows-msvc",
            "llama-server.exe",
            "37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b",
        ),
    ],
)
def test_native_bash_archive_layouts(tmp_path, target, binary, digest):
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "fetch-llama-server.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / script.name, script)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    executable = fixture / binary
    executable.write_text("#!/bin/sh\necho 'build 11669'\n")
    executable.chmod(0o755)
    library = fixture / "runtime-library"
    library.write_text("fixture dependency")
    archive = tmp_path / "archive"
    if binary.endswith(".exe"):
        with zipfile.ZipFile(archive, "w") as z:
            z.write(executable, binary)
            z.write(library, library.name)
    else:
        with tarfile.open(archive, "w:gz") as t:
            t.add(fixture, arcname="llama-b11669")
    fixture_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    script.write_text(script.read_text().replace(digest, fixture_digest))
    commands = tmp_path / "commands"
    commands.mkdir()
    for name, code in {
        "curl": (
            '#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nshift\n'
            'cp "$FIXTURE_ARCHIVE" "$1"\n'
        ),
    }.items():
        p = commands / name
        p.write_text(code)
        p.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(commands) + os.pathsep + os.environ["PATH"],
        FIXTURE_ARCHIVE=str(archive),
        FIXTURE_SHA=digest,
    )
    result = subprocess.run(
        ["/bin/bash", str(script), target], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    resource = root / "tauri-shell/src-tauri/resources/llama-server"
    assert (resource / binary).is_file()
    assert (resource / library.name).read_text() == "fixture dependency"
