# TeXada Architecture

Version: v0.1.0. TeXada is an endpoint-first math formula agent: it defaults to local Ollama MiniCPM models and can switch to any OpenAI-compatible `/v1/chat/completions` provider.

## System Overview

```
Browser / Tauri desktop shell
        |
        | starts bundled backend sidecar if the API is not already running
        | HTTP API, native clipboard, tray, global shortcut
        v
FastAPI backend (TEXADA_API_HOST:TEXADA_API_PORT)
        |
        +--> deterministic pipeline
        |    intent, symbols, shorthand, validator, fixer, renderer
        |
        +--> model pipeline
             OpenAI-compatible chat API
             - Ollama local endpoint (default: http://localhost:11434/v1)
             - Custom OpenAI-compatible endpoint
```

The local Ollama port is not fixed. The default is `http://localhost:11434`, but users can change it with the Settings UI, `~/.texada/config.json`, or `TEXADA_OLLAMA_HOST`.

The FastAPI address and the Ollama address are separate layers. `TEXADA_API_HOST:TEXADA_API_PORT` is where the desktop shell reaches TeXada's own `/api/*` routes. Release installers bundle this FastAPI backend as a PyInstaller sidecar and start it automatically when the API is not already reachable. `TEXADA_OLLAMA_HOST` is where the FastAPI backend reaches local model APIs and appends `/v1` internally. They should not be set to the same port unless a custom proxy intentionally combines both roles.

## Backend

| Module | Responsibility |
|--------|----------------|
| `config.py` | Pydantic settings from `~/.texada/config.json` plus `TEXADA_` environment variables |
| `api.py` | FastAPI app factory and HTTP endpoints |
| `sidecar.py` | Packaged FastAPI entry point used by desktop installers |
| `core/router.py` | Routes natural language, completion, OCR, and shorthand requests |
| `core/backend.py` | Checks local Ollama or cloud endpoint readiness |
| `core/model.py` | OpenAI-compatible chat wrapper for text and vision models |
| `core/validator.py`, `core/fixer.py` | LaTeX validation and repair |
| `render/engine.py` | KaTeX and LaTeX highlighting |
| `store/` | SQLite history and shorthand storage |

Clipboard, paste and notifications are handled in the Tauri shell for desktop builds. The old Python platform adapter layer was removed because it was no longer used by the API or installer builds.

## Models

| Role | Default | Notes |
|------|---------|-------|
| Local text | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | Natural language to LaTeX and fallback completion |
| Local vision | `openbmb/minicpm-v4.6:latest` | OCR for handwritten or screenshot formulas |
| Cloud text/vision | User-provided OpenAI-compatible models | Endpoint, model, vision model and API key are user settings |

MiniCPM5 can emit the answer in a `reasoning` field with empty `content`, so the model wrapper falls back to extracting LaTeX from either field.

## Frontend

The active UI lives in `tauri-shell/src/` and has no build step.

- Tabs: NL, OCR, completion, snippets, history, settings.
- Settings persist UI language, UI zoom, local Ollama host, local model names and cloud model credentials.
- Formula blocks type into the current system cursor in desktop mode; copy buttons still copy.
- Header and neutral panel surfaces call the Tauri native `start_dragging` command; form controls, tabs, formula blocks and other interactive targets are excluded so IME composition and clicks remain stable.
- Browser development falls back to clipboard copy for insert-at-cursor behavior.

## Desktop Shell

The release desktop shell is Tauri only:

| Path | Role |
|------|------|
| `tauri-shell/src-tauri/` | Rust shell, tray icon, global shortcut, native clipboard, window drag and bundle config |
| `tauri-shell/src/` | Static frontend bundled into the Tauri app |
| `scripts/build-windows-app.ps1` | Windows local NSIS build helper |
| `scripts/build-backend-sidecar.py` | Builds the real PyInstaller backend sidecar for release or a stub for `cargo check` |
| `scripts/generate-app-icons.py` | Rebuilds the source PNG, macOS ICNS, Windows ICO and Tauri PNG icons |
| `.github/workflows/release-desktop.yml` | macOS arm64 DMG, macOS Intel DMG and Windows x64 NSIS release build |

The old Swift WKWebView shell and v1 prototype archive were removed because they were not part of the release build and duplicated current code paths.

## Configuration

Persistent config lives at `~/.texada/config.json`. Environment variables override config values.

Important variables:

| Variable | Purpose |
|----------|---------|
| `TEXADA_BACKEND` | `ollama` or `openai_compatible` |
| `TEXADA_OLLAMA_HOST` | Local Ollama base URL, any host/port |
| `TEXADA_MODEL_NAME`, `TEXADA_VISION_MODEL_NAME` | Local text and vision model names |
| `TEXADA_OPENAI_BASE_URL` | Full OpenAI-compatible cloud base URL |
| `TEXADA_OPENAI_MODEL_NAME`, `TEXADA_OPENAI_VISION_MODEL_NAME` | Cloud text and vision model names |
| `TEXADA_OPENAI_API_KEY` | Cloud provider API key |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI bind address |
| `TEXADA_API_BASE` | Explicit desktop shell API base |
| `TEXADA_DISABLE_BUNDLED_BACKEND` | Disable automatic sidecar startup for custom backend management |
| `TEXADA_API_TIMEOUT_SECS` | Tauri API request timeout |
| `TEXADA_INFERENCE_TIMEOUT_SECONDS`, `TEXADA_API_REQUEST_TIMEOUT_SECONDS` | Backend model and API request timeouts |

## CI And Release

- `Audit`: Ruff, pytest, pip-audit, npm audit, JS syntax check and Tauri `cargo check` on macOS and Windows. The Rust check creates a generated backend stub only to satisfy Tauri `externalBin` resolution.
- `Desktop Release`: runs pre-release audit, builds the real PyInstaller FastAPI sidecar, builds signed and notarized macOS DMGs plus the Windows NSIS EXE, and publishes the official release assets.
- macOS signing and notarization are controlled by repository secrets only. The workflow expects `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_TEAM_ID`, `APPLE_NOTARY_KEY_ID`, `APPLE_NOTARY_ISSUER_ID`, and `APPLE_NOTARY_KEY`; personal certificate contents are not documented in the repo.
- Source-run shell launchers and macOS LaunchAgent templates are intentionally not kept; packaged desktop releases are the supported user path.

## Current Cleanup Policy

Tracked source should describe one current app. Generated caches, local dependencies, archives, stale prototypes and compiled binaries are not kept in git.
