# File Inventory / 文件清单

This inventory covers the tracked files in TeXada-the-Math-Agent after the community-standard pass. Generated caches, local virtual environments, build outputs, installers, logs, and runtime user data under `~/.texada` are intentionally not tracked.

本清单覆盖 TeXada-the-Math-Agent 当前纳入 git 的文件。缓存、本地虚拟环境、构建产物、安装包、日志和 `~/.texada` 下的运行时用户数据不纳入仓库。

## Repository Health / 仓库健康文件

| File | Purpose |
|------|---------|
| `README.md` | Bilingual user-facing product guide, release-package install path, Ollama quick start, cloud mode, shortcuts, hardware notes, and quality gate. |
| `LICENSE` | GPL-3.0-or-later license text. |
| `CHANGELOG.md` | Human-readable release history for 0.1.0 and later. |
| `.github/CODEOWNERS` | Assigns repository ownership and review responsibility to `@CacinieP`. |
| `.github/CODE_OF_CONDUCT.md` | Community conduct expectations and reporting route. |
| `.github/CONTRIBUTING.md` | Contribution workflow, no hard-coded interfaces, no production mock data, test expectations, and PR rules. |
| `.github/SECURITY.md` | Supported versions and private vulnerability reporting policy. |
| `.github/SUPPORT.md` | Support route, Ollama/model checklist, and public issue safety reminders. |
| `.github/pull_request_template.md` | Default PR checklist for scope, validation, backend coverage, and secret safety. |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | Structured bug-report issue form. |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | Structured feature-request issue form. |
| `.github/ISSUE_TEMPLATE/config.yml` | Disables blank issues and routes security reports to private advisories. |
| `.editorconfig` | Cross-editor whitespace, charset, newline, and indentation defaults. |
| `.gitattributes` | Text normalization and binary classification for images/installers. |

## Project Configuration / 项目配置

| File | Purpose |
|------|---------|
| `.env.example` | Illustrative environment variables for local Ollama, API, web, and UI configuration. |
| `.gitignore` | Excludes local caches, virtual environments, build outputs, logs, runtime artifacts, and generated bundles. |
| `pyproject.toml` | Python package metadata, dependencies, optional dev tools, hatch build settings, Ruff, and pytest config. |
| `uv.lock` | Locked Python dependency snapshot for reproducible `uv` installs. |
| `package.json` | Node metadata and KaTeX CLI dependency used by rendering validation. |
| `package-lock.json` | Locked npm dependency snapshot for KaTeX and its CLI dependency. |

## Documentation / 文档

| File | Purpose |
|------|---------|
| `docs/README.md` | Documentation index grouping technical docs and root-level community/release files. |
| `docs/architecture.md` | High-level architecture, model/backend choices, desktop shell, configuration, and CI overview. |
| `docs/audit.md` | Source audit scope, stale-code removals, remediation history, and intentional defaults. |
| `docs/file-inventory.md` | This file-by-file source map. |
| `docs/technical-report.md` | Technical rationale, model selection, deterministic pipeline design, performance measurements, and known limitations. |

## Python Backend / Python 后端

| File | Purpose |
|------|---------|
| `src/texada/__init__.py` | Package metadata and runtime version lookup. |
| `src/texada/__main__.py` | Typer CLI for serving the API, one-shot conversion, and readiness checks. |
| `src/texada/api.py` | FastAPI app factory, CORS/origin guard, conversion/OCR/completion/history/settings/runtime endpoints. |
| `src/texada/config.py` | Pydantic settings from environment and `~/.texada/config.json`, including Ollama/cloud/UI persistence. |
| `src/texada/sidecar.py` | FastAPI entry point packaged into the desktop installer as the bundled backend sidecar. |
| `src/texada/types.py` | Shared enums and dataclasses for routing, rendering, validation, conversion, history, and legacy compatibility. |
| `src/texada/core/__init__.py` | Core package marker. |
| `src/texada/core/backend.py` | Ollama/OpenAI-compatible readiness checks, model presence detection, custom port handling, and status payloads. |
| `src/texada/core/fixer.py` | Deterministic LaTeX repair for common brace, environment, and command mistakes. |
| `src/texada/core/intent.py` | Regex-based intent classifier for math categories without model calls. |
| `src/texada/core/model.py` | OpenAI-compatible chat wrapper for text, completion, vision OCR, timeout handling, and LaTeX extraction. |
| `src/texada/core/ocr.py` | OCR pipeline wrapper around the configured vision model. |
| `src/texada/core/prompts.py` | System prompts and intent-specific few-shot examples for NL, completion, and OCR. |
| `src/texada/core/router.py` | Request routing across natural language, completion, OCR, shorthand, validation/fix, rendering, and drift retry. |
| `src/texada/core/symbols.py` | Deterministic Chinese math term to LaTeX pre-translation table. |
| `src/texada/core/validator.py` | Multi-layer LaTeX validation using braces, environments, commands, and optional KaTeX parsing. |
| `src/texada/render/__init__.py` | Render package marker. |
| `src/texada/render/engine.py` | KaTeX and pure-LaTeX render mode engine plus copy text delimiters. |
| `src/texada/render/highlighter.py` | Lightweight semantic LaTeX highlighter for pure source mode. |
| `src/texada/store/__init__.py` | Store package marker. |
| `src/texada/store/history.py` | SQLite-backed conversion history store with cleanup support. |
| `src/texada/store/shorthand.py` | Built-in and user-defined shorthand formula store backed by JSON. |

## Desktop Frontend And Shell / 桌面前端与壳

| File | Purpose |
|------|---------|
| `tauri-shell/src/api-config.js` | Browser/Tauri API base resolution from shell bridge, query, localStorage, meta tags, or default local port. |
| `tauri-shell/src/index.html` | Static UI structure for tabs, settings, results, OCR, snippets, history, and status. |
| `tauri-shell/src/main.js` | Frontend controller for API calls, tabs, i18n, zoom, drag behavior, OCR, snippets, history, copy, and insert-at-cursor. |
| `tauri-shell/src/style.css` | Dark floating-panel UI, responsive layout, status, forms, result blocks, zoom, and interaction styling. |
| `tauri-shell/src/app-icon.png` | 128px app icon shown in the static UI header. |
| `tauri-shell/src-tauri/Cargo.toml` | Rust/Tauri package metadata and dependencies for desktop shell features. |
| `tauri-shell/src-tauri/Cargo.lock` | Locked Rust dependency snapshot for reproducible Tauri builds. |
| `tauri-shell/src-tauri/build.rs` | Tauri build-script entrypoint. |
| `tauri-shell/src-tauri/src/main.rs` | Native desktop shell: bundled backend sidecar startup, API proxy, clipboard, paste insertion, tray, global shortcut, window show/hide, and drag command. |
| `tauri-shell/src-tauri/tauri.conf.json` | Tauri app identity, window settings, permissions, CSP, bundle targets, backend external binary, icons, and macOS signing placeholder. |
| `tauri-shell/src-tauri/icons/32x32.png` | Tauri PNG icon for small app surfaces. |
| `tauri-shell/src-tauri/icons/128x128.png` | Tauri PNG icon for standard app surfaces. |
| `tauri-shell/src-tauri/icons/128x128@2x.png` | Tauri high-DPI PNG icon. |
| `tauri-shell/src-tauri/icons/icon.icns` | macOS app icon bundle. |
| `tauri-shell/src-tauri/icons/icon.ico` | Windows app icon bundle. |

## Assets / 资产

| File | Purpose |
|------|---------|
| `assets/TeXada-icon-source.png` | 1024px source icon generated by `scripts/generate-app-icons.py`. |
| `assets/clipboard-screenshot.png` | README screenshot of the current desktop UI. |
| `assets/texada-hero.png` | README hero image showing TeXada branding, math notes, GPL-3.0 licensing, and a real formula demo. |

## Launch, Build, And Release / 启动、构建与发布

| File | Purpose |
|------|---------|
| `scripts/build-backend-sidecar.py` | Builds the real PyInstaller FastAPI sidecar for installers or a generated stub for Tauri `cargo check`. |
| `scripts/build-windows-app.ps1` | Windows helper for local Tauri NSIS installer builds. |
| `scripts/generate-app-icons.py` | Generates source PNG, Tauri PNGs, macOS ICNS, and Windows ICO icons. |
| `.github/workflows/audit.yml` | CI audit workflow for Python, npm, JS syntax, generated sidecar stubs, and cross-platform Tauri `cargo check`. |
| `.github/workflows/release-desktop.yml` | Official release workflow for audited Windows NSIS and signed/notarized macOS DMG builds with bundled FastAPI sidecars. |

## Tests / 测试

| File | Purpose |
|------|---------|
| `tests/test_api.py` | FastAPI route, CORS, runtime, upload, settings, and key-safety tests. |
| `tests/test_backend.py` | Backend readiness/status tests for OpenAI-compatible config and Ollama missing-model states. |
| `tests/test_e2e.py` | Optional live API E2E tests gated by `TEXADA_RUN_E2E=1`. |
| `tests/test_fixer.py` | LaTeX auto-fixer tests. |
| `tests/test_highlighter.py` | Pure LaTeX syntax highlighter tests. |
| `tests/test_history.py` | SQLite history store tests. |
| `tests/test_intent.py` | Regex intent classifier tests. |
| `tests/test_operator_drift.py` | Regression tests for dropped/downgraded math operators. |
| `tests/test_render_engine.py` | KaTeX/pure-LaTeX render mode and delimiter tests. |
| `tests/test_router.py` | Input routing, shorthand, model-call dispatch, render isolation, and memory-isolation tests. |
| `tests/test_shorthand.py` | Built-in and custom shorthand persistence tests. |
| `tests/test_symbols.py` | Deterministic symbol pre-translation tests. |
| `tests/test_validator.py` | LaTeX validator tests for braces, environments, and command parsing. |

## Current Conclusion / 当前结论

Every tracked file has a current purpose: source code, release packaging, CI, documentation, tests, generated icons, screenshots, or reproducible dependency locks. Files that were stale prototypes, duplicate package metadata, old desktop shells, generated caches, and unused artifacts have already been removed and remain ignored.
