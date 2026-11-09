"""Check host symbol requirements, including weak imports and version ordering."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'glibc_check', Path(__file__).parents[1] / 'scripts/check-linux-glibc.py'
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize('version', ['2.38', '2.39', '2.100'])
def test_rejects_newer_imports_including_weak(monkeypatch, tmp_path, version):
    (tmp_path / 'library.so').write_bytes(b'\x7fELFfake')
    monkeypatch.setattr(check.subprocess, 'check_output', lambda *a, **k:
                        f'000 w DF UND 000 (GLIBC_{version}) function')
    with pytest.raises(RuntimeError, match='exceed 2.35'):
        check.check_tree(tmp_path)


def test_ignores_definitions_and_accepts_older_imports(monkeypatch, tmp_path):
    (tmp_path / 'library.so').write_bytes(b'\x7fELFfake')
    (tmp_path / 'text').write_text('not an ELF')
    monkeypatch.setattr(check.subprocess, 'check_output', lambda *a, **k:
                        '000 g DF .text 000 GLIBC_2.39 definition\n'
                        '000 g DF UND 000 (GLIBC_2.9) old_import\n'
                        '000 g DF UND 000 (GLIBC_2.35) baseline_import')
    assert check.check_tree(tmp_path) == 1


def test_empty_package_cannot_pass(tmp_path):
    with pytest.raises(RuntimeError, match='No packaged ELF'):
        check.check_tree(tmp_path)
