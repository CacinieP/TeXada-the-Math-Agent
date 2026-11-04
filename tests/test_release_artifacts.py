"""Release collection rejects mismatched, incomplete or changed installation evidence."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "desktop_release", Path(__file__).parents[1] / "scripts/prepare-desktop-release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
COMMIT = "a" * 40
VERSION = "0.4.2"


def evidence(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    names = ["TeXada_0.4.2_aarch64.dmg", "TeXada_0.4.2_x64.dmg",
             "TeXada_0.4.2_x64-setup.exe", "texada_0.4.2_amd64.deb",
             "TeXada_0.4.2_amd64.AppImage"]
    for i, ((target, format_), _suffix) in enumerate(release.TARGETS.items()):
        installer = source / names[i]
        installer.write_bytes(b"synthetic installer fixture " + str(i).encode())
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        smoke = dict(target=target, format=format_, source_commit=COMMIT,
                     installer=installer.name, installer_sha256=digest, version=VERSION,
                     bundled_runtime_build=11669, model_inference_tested=False,
                     **dict.fromkeys(release.GATES, True))
        if format_ == "dmg":
            smoke["signature_verified"] = True
            notary = dict(target=target, source_commit=COMMIT, installer=installer.name,
                          installer_sha256=digest, status="Accepted", submission_id=f"test-{i}",
                          stapler_validated=True, gatekeeper_assessed=True)
            (source / f"notarization-{target}.json").write_text(json.dumps(notary))
        (source / f"smoke-{target}-{format_}.json").write_text(json.dumps(smoke))
    return source


def rewrite(path, **updates):
    data = json.loads(path.read_text())
    path.write_text(json.dumps(data | updates))


def test_complete_native_evidence_stages_five_packages_and_verifiable_checksums(tmp_path):
    source = evidence(tmp_path)
    output = tmp_path / "staged"
    manifest = release.collect(source, output, COMMIT, VERSION)
    assert manifest["installer_count"] == 5
    assert manifest["source_commit"] == COMMIT
    assert len(list(output.iterdir())) == 14  # 5 installers, 7 evidence, manifest, checksums.
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("failure", ["missing-package", "changed-package", "other-commit",
                                    "failed-smoke", "wrong-version", "wrong-runtime",
                                    "missing-signature", "failed-notary", "notary-old-bytes",
                                    "missing-format", "duplicate-evidence", "path-injection"])
def test_untrusted_or_incomplete_release_is_not_published(tmp_path, failure):
    source = evidence(tmp_path)
    smoke = source / "smoke-aarch64-apple-darwin-dmg.json"
    notary = source / "notarization-aarch64-apple-darwin.json"
    if failure == "missing-package":
        (source / "TeXada_0.4.2_aarch64.dmg").unlink()
    elif failure == "changed-package":
        (source / "TeXada_0.4.2_aarch64.dmg").write_bytes(b"changed after validation")
    elif failure == "other-commit":
        rewrite(smoke, source_commit="b" * 40)
    elif failure == "failed-smoke":
        rewrite(smoke, installed_desktop_started=False)
    elif failure == "wrong-version":
        rewrite(smoke, version="0.4.1")
    elif failure == "wrong-runtime":
        rewrite(smoke, bundled_runtime_build=11609)
    elif failure == "missing-signature":
        rewrite(smoke, signature_verified=False)
    elif failure == "failed-notary":
        rewrite(notary, gatekeeper_assessed=False)
    elif failure == "notary-old-bytes":
        rewrite(notary, installer_sha256="0" * 64)
    elif failure == "missing-format":
        (source / "smoke-x86_64-unknown-linux-gnu-appimage.json").unlink()
    elif failure == "duplicate-evidence":
        (source / "duplicate.json").write_bytes(smoke.read_bytes())
    else:
        rewrite(smoke, installer="../TeXada_0.4.2_aarch64.dmg")
    with pytest.raises(ValueError):
        release.collect(source, tmp_path / "staged", COMMIT, VERSION)
    assert not (tmp_path / "staged").exists()


def test_preflight_rejects_checkout_identity_before_loading_metadata(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-q", "--allow-empty",
                    "-m", "fixture"], check=True)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="expected source commit"):
        release.preflight(COMMIT, None)


def metadata_checkout(tmp_path):
    documents = {
        "pyproject.toml": '[project]\nversion = "0.4.2"\n',
        "package.json": '{"version":"0.4.2"}',
        "package-lock.json": '{"version":"0.4.2","packages":{"":{"version":"0.4.2"}}}',
        "tauri-shell/src-tauri/Cargo.toml": '[package]\nversion = "0.4.2"\n',
        "tauri-shell/src-tauri/Cargo.lock":
            '[[package]]\nname = "texada-shell"\nversion = "0.4.2"\n',
        "uv.lock": '[[package]]\nname = "texada"\nversion = "0.4.2"\n',
        "tauri-shell/src-tauri/tauri.conf.json": '{"version":"0.4.2"}',
        "src/texada/__init__.py": '__version__ = "0.4.2"\n',
        "src/texada/api.py": 'def _app_version():\n    return "0.4.2"\n',
        "tauri-shell/src/index.html": '<span>v0.4.2</span>',
        "CHANGELOG.md": '## 0.4.2 - 2026-11-04\n',
    }
    for name, content in documents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture"],
                   check=True)
    return subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                                   text=True).strip()


def test_preflight_checks_consistent_versions_and_writes_action_outputs(tmp_path, monkeypatch):
    # This synthetic checkout must not inherit the outer release job's tag.
    monkeypatch.delenv("GITHUB_REF", raising=False)
    commit = metadata_checkout(tmp_path)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    output = tmp_path / "action-output"
    result = release.preflight(commit, output)
    assert result == {"version": VERSION, "tag": "v0.4.2", "source_commit": commit}
    assert "source_commit=" + commit in output.read_text()
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v0.4.1")
    with pytest.raises(ValueError, match="release tag and source version disagree"):
        release.preflight(commit, None)
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v0.4.2")
    assert release.preflight(commit, None)["tag"] == "v0.4.2"
    (tmp_path / "package.json").write_text('{"version":"0.4.1"}')
    with pytest.raises(ValueError, match="tracked changes"):
        release.preflight(commit, None)
    subprocess.run(["git", "-C", str(tmp_path), "add", "package.json"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "stale"],
                   check=True)
    changed = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                                    text=True).strip()
    with pytest.raises(ValueError, match="metadata versions disagree"):
        release.preflight(changed, None)
