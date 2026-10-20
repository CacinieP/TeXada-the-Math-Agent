"""Exercise the release workflow assertions against the actual default API."""
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

from texada.api import create_app
from texada.config import TeXadaConfig


def test_installed_smoke_script_asserts_direct_commit():
    """The per-platform installed-package smoke must match the current contract.

    The release run failed on all three platforms because this script still
    asserted the removed human-review gate; pin the contract statically so a
    stale assertion cannot ship again.
    """
    script = (
        Path(__file__).parents[1] / "scripts" / "smoke-installed-desktop.py"
    ).read_text(encoding="utf-8")

    assert 'assert result["stop_reason"] == "deterministic_candidate", result' in script
    assert 'assert result["committed"] is True, result' in script
    assert 'assert result["review"] is None, result' in script
    assert "human_review_required" not in script
    assert "default_human_review_enforced" not in script


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_field', [None, 'committed', 'review', 'parser_backend'])
async def test_signed_sidecar_smoke_accepts_automatic_commit_and_rejects_tampering(
    tmp_path, invalid_field,
):
    app = create_app(TeXadaConfig(data_dir=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://test',
    ) as client:
        response = await client.post('/api/agent', json={'text': '二重积分'})
    assert response.status_code == 200
    payload = response.json()
    if invalid_field == 'committed':
        payload['committed'] = False
    elif invalid_field == 'review':
        payload['review'] = {'status': 'pending', 'reasons': ['nl_semantics_requires_review']}
    elif invalid_field == 'parser_backend':
        payload['semantic_document']['parser_backend'] = 'tampered'
    path = tmp_path / 'response.json'
    path.write_text(json.dumps(payload))
    workflow = (Path(__file__).parents[1] / '.github/workflows/release-desktop.yml').read_text()
    match = re.search(r'''RESPONSE_PATH="\$response" python -c '(.*?)\n          '\n''',
                      workflow, re.DOTALL)
    assert match is not None
    result = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(match[1])],
        env=dict(os.environ, RESPONSE_PATH=str(path)), capture_output=True, text=True,
    )
    assert (result.returncode == 0) is (invalid_field is None), result.stderr
