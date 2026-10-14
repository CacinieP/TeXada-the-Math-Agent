"""Exercise the actual review UI with a DOM that rejects unsafe HTML sinks."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_revision_bound_review_ui_behaviour():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for review UI behaviour tests")
    result = subprocess.run(
        [node, "--test", "tests/review-ui.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_review_module_is_loaded_before_main_frontend():
    html = (ROOT / "tauri-shell/src/index.html").read_text(encoding="utf-8")
    assert html.index('src="review-ui.js') < html.index('src="main.js')


def test_browser_and_tauri_allow_only_loopback_review_images():
    html = (ROOT / "tauri-shell/src/index.html").read_text(encoding="utf-8")
    config = json.loads(
        (ROOT / "tauri-shell/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    for policy in (html, config["app"]["security"]["csp"]):
        images = policy.split("img-src ", 1)[1].split(";", 1)[0].split()
        assert set(images) == {
            "'self'", "data:", "blob:", "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
        }
