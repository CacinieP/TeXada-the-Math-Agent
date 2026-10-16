"""Execute the workflow's actual flag selection: RC must never become latest."""
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parents[1] / '.github/workflows/release-desktop.yml'


@pytest.mark.parametrize('version,expected', [
    ('0.4.2-rc.1', ['--draft', '--prerelease', '--latest=false']),
    ('0.4.2-beta.4', ['--draft', '--prerelease', '--latest=false']),
    ('0.4.2', ['--latest']),
])
def test_workflow_release_flags(version, expected):
    source = WORKFLOW.read_text()
    begin = source.index('          release_flags=')
    selection = source[begin:source.index('          gh release create')]
    result = subprocess.run(
        ['bash', '-c', selection + '\n printf "%s\\n" "${release_flags[@]}"'],
        env={'version': version}, text=True, capture_output=True, check=True,
    )
    assert result.stdout.splitlines() == expected
