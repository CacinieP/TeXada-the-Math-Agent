# TeXada Source Audit

Scope: `/Users/caciniep/Desktop/TeXada-the-Math-Agent` only.

## Source Map

| Area | Paths | Status |
|------|-------|--------|
| Python backend | `src/texada/` | Current FastAPI API, routing, model client, rendering, stores, platform adapters |
| Desktop UI | `tauri-shell/src/` | Current static UI used by Tauri and browser development |
| Tauri shell | `tauri-shell/src-tauri/` | Current macOS/Windows desktop shell, tray, shortcut, signing and bundling config |
| Build/ops | `scripts/`, `.github/workflows/`, `TeXada.command`, `start.sh` | Current launch, service and CI entrypoints |
| Tests | `tests/` | Unit/API/E2E coverage |
| Docs | `README.md`, `TECHNICAL_REPORT.md`, `docs/architecture.md` | Current documentation |

Excluded from source: `.venv/`, `node_modules/`, `target/`, `.ruff_cache/`, `.pytest_cache/`, generated app bundles, `.dmg`/`.exe` artifacts, runtime logs, and user data under `~/.texada`.

## Findings

1. The legacy Swift WKWebView shell and its compiled Mach-O binary duplicated the Tauri shell and were not part of the release workflow.
2. `v1-archive/`, `docs/design.md`, and `docs/ui-mockup.html` described old prototypes instead of the current application.
3. `requirements.txt` duplicated `pyproject.toml` dependency declarations.
4. CI still syntax-checked the deleted legacy Swift shell assets.
5. `package.json` and `package-lock.json` still declared MIT while the repository license is GPL.
6. `start.sh` and `TeXada.command` assumed Ollama always lived on `localhost:11434`.
7. The UI persisted language but not zoom, and desktop drag relied only on CSS drag regions.

## Remediation

1. Removed the legacy Swift shell, `v1-archive/`, stale design/mockup docs, and duplicate `requirements.txt`.
2. Kept the release surface to one desktop implementation: Tauri shell plus static frontend.
3. Updated GitHub Actions to audit only current frontend sources.
4. Aligned npm metadata with `GPL-3.0-or-later`.
5. Made launcher scripts read `TEXADA_OLLAMA_HOST`, `TEXADA_API_*`, `TEXADA_WEB_*`, and `~/.texada/config.json`.
6. Added persisted UI zoom (`80%` to `140%`) and keyboard zoom shortcuts.
7. Added a Tauri `start_dragging` command so the header can move the window reliably.

## Remaining Intentional Defaults

- `http://localhost:11434` is only the default Ollama endpoint. Users can change it in Settings, `~/.texada/config.json`, or `TEXADA_OLLAMA_HOST`.
- `127.0.0.1:18732` and `127.0.0.1:5173` are default local API/web ports, not fixed cloud or model endpoints.
- macOS release packages are signed with the configured Apple certificate. Notarization is separate and requires Developer ID/notary credentials.
