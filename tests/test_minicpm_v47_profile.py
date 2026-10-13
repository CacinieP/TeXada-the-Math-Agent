"""Execute the opt-in launcher without starting a service or calling an API."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "run-minicpm-v47.sh"


@pytest.fixture
def launch_profile(tmp_path):
    bin_dir = tmp_path / "fake bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$PWD" "$*" "$TEXADA_BACKEND" '
        '"$TEXADA_OPENAI_BASE_URL" "$TEXADA_OPENAI_MODEL_NAME" '
        '"$TEXADA_OPENAI_VISION_MODEL_NAME" "$TEXADA_NL_CANDIDATE_FIRST" '
        '"$TEXADA_OCR_PREPROCESSING"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith("TEXADA_")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    def run(updates, *args):
        return subprocess.run(
            ["/bin/sh", str(LAUNCHER), *args],
            cwd=tmp_path,
            env={**env, **updates},
            capture_output=True,
            text=True,
            check=False,
        )

    return run


@pytest.mark.parametrize("base_url", [None, "http://127.0.0.1:8080/v1"])
def test_profile_selects_one_checkpoint_from_any_working_directory(launch_profile, base_url):
    key = "test-credential-must-never-be-printed"
    updates = {
        "TEXADA_OPENAI_API_KEY": key, "TEXADA_BACKEND": "ollama",
        "TEXADA_NL_CANDIDATE_FIRST": "false",
        "TEXADA_OCR_PREPROCESSING": "binary",
    }
    if base_url is not None:
        updates["TEXADA_OPENAI_BASE_URL"] = base_url

    result = launch_profile(updates, "--port", "18733")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(ROOT),
        "run --no-sync texada serve --port 18733",
        "openai_compatible",
        base_url or "https://api.modelbest.cn/v1",
        "MiniCPM-V-4.7-1B",
        "MiniCPM-V-4.7-1B",
        "true",
        "raw",
    ]
    assert key not in result.stdout + result.stderr


def test_profile_requires_an_environment_key_before_launching(launch_profile):
    result = launch_profile({})

    assert result.returncode == 2
    assert not result.stdout
    assert "TEXADA_OPENAI_API_KEY" in result.stderr
    assert "local-no-key" in result.stderr


@pytest.mark.parametrize("role", ["TEXADA_OPENAI_MODEL_NAME", "TEXADA_OPENAI_VISION_MODEL_NAME"])
def test_profile_rejects_a_second_checkpoint_without_disclosing_values(launch_profile, role):
    key = "test-credential-must-never-be-printed"
    conflicting_model = "test-conflicting-model"
    result = launch_profile({"TEXADA_OPENAI_API_KEY": key, role: conflicting_model})

    assert result.returncode == 2
    assert not result.stdout
    assert role in result.stderr
    assert "MiniCPM-V-4.7-1B" in result.stderr
    assert key not in result.stderr
    assert conflicting_model not in result.stderr
