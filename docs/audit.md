# TeXada Source Audit

> Scope: only `/Users/caciniep/Desktop/TeXada-the-Math-Agent`.

## Source Map

| Area | Paths | Notes |
|------|-------|-------|
| Python backend | `src/texada/` | FastAPI API, routing, model client, rendering, stores, platform adapters |
| Static desktop UI | `tauri-shell/src/` | Tauri frontend assets loaded by the cross-platform shell |
| Tauri shell | `tauri-shell/src-tauri/` | macOS/Windows desktop bridge, tray, shortcuts, bundling config |
| Legacy Swift shell | `tauri-shell/TeXadaShell/TeXadaShell/` | macOS WKWebView shell kept as source, not the release build path |
| Build/ops | `scripts/`, `.github/workflows/` | LaunchAgent templates, local build scripts, GitHub Actions |
| Tests | `tests/` | Unit/API/E2E coverage |
| Docs | `README.md`, `docs/` | Architecture and user-facing build instructions |

Excluded from source: `node_modules/`, `target/`, generated `.app` bundles, `.dmg`/`.exe` artifacts, and local runtime data under `~/.texada`.

## Findings

1. Desktop UI, Tauri Rust, and legacy Swift code duplicated a fixed API endpoint.
2. Frontend OCR upload validation duplicated backend limits.
3. Python CLI started uvicorn with fixed host/port instead of the shared config.
4. `MiniCPMModel` used an unreachable placeholder endpoint when OpenAI-compatible settings were incomplete.
5. LaunchAgent templates bound services to fixed host/port and could drift from runtime config.
6. Release workflow existed but used moving runner labels for release builds.

## Remediation

1. Added runtime API config via `/api/runtime`.
2. Centralized desktop API resolution through `TEXADA_API_BASE`, `TEXADA_API_HOST`, and `TEXADA_API_PORT`.
3. Routed Tauri JSON requests through a native bridge command instead of scattering fetch endpoints.
4. Made the OpenAI-compatible client lazy and explicit about missing endpoint/key/model.
5. Templated LaunchAgent host/port and propagated API env vars into the backend process.
6. Updated GitHub Actions to build macOS `.dmg` and Windows NSIS `.exe` on pinned current runners.
