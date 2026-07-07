# TeXada Architecture

Version: v0.3.0. TeXada is an endpoint-first math formula agent: it defaults to local Ollama MiniCPM models and can switch to any OpenAI-compatible `/v1/chat/completions` provider.

## System Overview

```
Browser / Tauri desktop shell
        |
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

## Backend

| Module | Responsibility |
|--------|----------------|
| `config.py` | Pydantic settings from `~/.texada/config.json` plus `TEXADA_` environment variables |
| `api.py` | FastAPI app factory and HTTP endpoints |
| `core/router.py` | Routes natural language, completion, OCR, and shorthand requests |
| `core/backend.py` | Checks local Ollama or cloud endpoint readiness |
| `core/model.py` | OpenAI-compatible chat wrapper for text and vision models |
| `core/validator.py`, `core/fixer.py` | LaTeX validation and repair |
| `render/engine.py` | KaTeX and LaTeX highlighting |
| `store/` | SQLite history and shorthand storage |

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
- Header drag calls the Tauri native `start_dragging` command.
- Browser development falls back to clipboard copy for insert-at-cursor behavior.

## Desktop Shell

The release desktop shell is Tauri only:

| Path | Role |
|------|------|
| `tauri-shell/src-tauri/` | Rust shell, tray icon, global shortcut, native clipboard, window drag and bundle config |
| `tauri-shell/src/` | Static frontend bundled into the Tauri app |
| `scripts/build-windows-app.ps1` | Windows local NSIS build helper |
| `.github/workflows/release-desktop.yml` | macOS arm64 DMG, macOS Intel DMG and Windows x64 NSIS release build |

The old Swift WKWebView shell and v1 prototype archive were removed because they were not part of the release build and duplicated current code paths.

## Configuration

Persistent config lives at `~/.texada/config.json`. Environment variables override config values.

Important variables:

| Variable | Purpose |
|----------|---------|
| `TEXADA_OLLAMA_HOST` | Local Ollama base URL, any host/port |
| `TEXADA_API_HOST`, `TEXADA_API_PORT` | FastAPI bind address |
| `TEXADA_WEB_HOST`, `TEXADA_WEB_PORT` | Local static web launcher address |
| `TEXADA_API_BASE` | Explicit desktop shell API base |
| `TEXADA_API_TIMEOUT_SECS` | Tauri API request timeout |

## CI And Release

- `Audit`: Ruff, pytest, pip-audit, npm audit, JS syntax check and Tauri `cargo check` on macOS and Windows.
- `Desktop Release`: runs pre-release audit, builds signed macOS DMGs and Windows NSIS EXE, and uploads draft release assets.
- macOS signing requires `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY` and `APPLE_TEAM_ID` secrets.

## Current Cleanup Policy

Tracked source should describe one current app. Generated caches, local dependencies, archives, stale prototypes and compiled binaries are not kept in git.
