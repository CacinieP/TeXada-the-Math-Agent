"""Archive layout fixtures; no network or actual package integrity validation."""

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
            "96623092033e83545cd92316ff63d0378a976a4979735f80a1934cc128efb0ad",
        ),
        (
            "x86_64-apple-darwin",
            "llama-server",
            "df796167a64469d8ab805a71aadc9a531982f0b0d86a9b449df5fe72af26a065",
        ),
        (
            "x86_64-pc-windows-msvc",
            "llama-server.exe",
            "dece5ebc80fbc48063540aa4c48fdc91c59328b7ea44c2bdf6e85ec4383b5fc7",
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
    executable.write_text("#!/bin/sh\necho 'build 11046'\n")
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
            t.add(fixture, arcname="llama-b11046")
    commands = tmp_path / "commands"
    commands.mkdir()
    for name, code in {
        "curl": (
            '#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nshift\n'
            'cp "$FIXTURE_ARCHIVE" "$1"\n'
        ),
        "shasum": '#!/bin/sh\necho "$FIXTURE_SHA  fixture"\n',
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
