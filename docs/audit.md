# TeXada Source Audit

Scope: `/Users/caciniep/Desktop/TeXada-the-Math-Agent` only.

## Source Map

| Area | Paths | Status |
|------|-------|--------|
| Python backend | `src/texada/` | Current FastAPI API, routing, model client, rendering and stores |
| Desktop UI | `tauri-shell/src/` | Current static UI used by Tauri and browser development |
| Tauri shell | `tauri-shell/src-tauri/` | Current macOS/Windows desktop shell, tray, shortcut, backend sidecar startup, signing and bundling config |
| Build/ops | `scripts/`, `.github/workflows/` | Current icon generation, Windows helper and CI/release entrypoints |
| Tests | `tests/` | Unit/API/E2E coverage |
| Docs | `README.md`, root community files, `CHANGELOG.md`, `docs/` | Current user, community and technical documentation |

Excluded from source: `.venv/`, `node_modules/`, `target/`, `.ruff_cache/`, `.pytest_cache/`, generated app bundles, `.dmg`/`.exe` artifacts, runtime logs, and user data under `~/.texada`.

## Findings

1. The legacy Swift WKWebView shell and its compiled Mach-O binary duplicated the Tauri shell and were not part of the release workflow.
2. `v1-archive/`, `docs/design.md`, and `docs/ui-mockup.html` described old prototypes instead of the current application.
3. `requirements.txt` duplicated `pyproject.toml` dependency declarations.
4. CI still syntax-checked the deleted legacy Swift shell assets.
5. `package.json` and `package-lock.json` still declared MIT while the repository license is GPL.
6. `start.sh`, `TeXada.command`, and LaunchAgent scripts were source-run service paths that conflicted with the distribution-package-first release direction.
7. The UI persisted language but not zoom, and desktop drag relied only on CSS drag regions.
8. The Python `platform/` and `output/clipboard.py` adapters were leftovers from a pre-Tauri desktop path; current macOS/Windows clipboard and paste behavior lives in the Tauri shell.
9. `assets/TeXada.icns` duplicated `tauri-shell/src-tauri/icons/icon.icns` byte-for-byte and was not referenced by the release workflow.

## Remediation

1. Removed the legacy Swift shell, `v1-archive/`, stale design/mockup docs, and duplicate `requirements.txt`.
2. Kept the release surface to one desktop implementation: Tauri shell plus static frontend.
3. Updated GitHub Actions to audit only current frontend sources.
4. Aligned npm metadata with `GPL-3.0-or-later`.
5. Removed source-run launcher and LaunchAgent scripts; the release surface is now the packaged Tauri app plus GitHub Actions installers.
6. Added persisted UI zoom (`80%` to `140%`) and keyboard zoom shortcuts.
7. Added a Tauri `start_dragging` command so the header can move the window reliably.
8. Removed unused Python platform/output clipboard adapters and their stale dependencies.
9. Removed the duplicate root `.icns` artifact; `scripts/generate-app-icons.py` now writes only the Tauri bundle icons plus the source PNG.
10. Added a packaged PyInstaller FastAPI sidecar so release installers open without a separate Python/API server setup.

## Remaining Intentional Defaults

- `http://localhost:11434` is only the default Ollama endpoint. Users can change it in Settings, `~/.texada/config.json`, or `TEXADA_OLLAMA_HOST`.
- `127.0.0.1:18732` is the default bundled FastAPI sidecar port used by the desktop shell; it is separate from the Ollama/model endpoint.
- `127.0.0.1:5173` and `127.0.0.1:1420` are development origins allowed by CORS/CSP, not required user-facing model endpoints.
- macOS release package signing, when enabled, is driven only by repository secrets; no personal certificate details are stored in the docs.
