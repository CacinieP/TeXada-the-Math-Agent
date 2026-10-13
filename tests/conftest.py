import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))


@pytest.fixture(autouse=True)
def isolated_user_settings(monkeypatch, tmp_path):
    """Deterministic tests must not read credentials or settings from the desktop."""
    import os

    from texada.config import TeXadaConfig

    monkeypatch.setitem(TeXadaConfig.model_config, "json_file", str(tmp_path / "config.json"))
    for name in os.environ:
        if name.startswith("TEXADA_"):
            monkeypatch.delenv(name, raising=False)
