# Contributing / 贡献指南

## English

Thanks for improving TeXada. This repository ships a desktop math formula agent, so changes should keep the current release surface focused: FastAPI backend, static web UI, Tauri desktop shell, docs, tests, and release workflows.

### What To Include

- Describe the user-facing problem and the platform affected: macOS, Windows, browser development, Ollama, or OpenAI-compatible cloud mode.
- Keep interfaces configurable. Do not hard-code model endpoints, API keys, Ollama ports, or provider-specific assumptions.
- Do not add fake product paths, mock data, or placeholder integrations to production code. Unit tests may mock external model calls when the real dependency would make tests slow or non-deterministic.
- Update docs when behavior, settings, shortcuts, models, or installer behavior changes.
- Add or update focused tests for backend routing, validation, settings persistence, UI regressions, or release scripts when relevant.

### Local Checks

Run the focused checks before opening a pull request:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
npm audit --audit-level=moderate
node --check tauri-shell/src/main.js
cd tauri-shell/src-tauri && cargo check
```

For security-sensitive work, also run:

```bash
uvx pip-audit --strict
```

### Pull Requests

- Use the pull request template.
- Keep each PR scoped to one purpose.
- Include screenshots or short recordings for UI changes.
- Mention the tested backend: local Ollama, custom Ollama port, OpenAI-compatible cloud endpoint, or both.
- Never commit secrets, personal signing certificates, private API keys, runtime databases, logs, build outputs, or generated installers.

## 中文

感谢你改进 TeXada。本仓库发布的是桌面数学公式 Agent，所以变更应围绕当前发布面：FastAPI 后端、静态前端、Tauri 桌面壳、文档、测试和 release workflow。

### 贡献内容要求

- 说明用户问题和受影响平台：macOS、Windows、浏览器开发、Ollama、本地模型或 OpenAI-compatible 云侧模式。
- 接口必须可配置。不要写死模型 endpoint、API key、Ollama 端口或某个 provider 的隐含假设。
- 生产代码不要加入假的产品路径、mock 数据或占位接口。单元测试可以 mock 外部模型调用，用来保持测试快速、稳定、可重复。
- 行为、设置、快捷键、模型或安装包流程变化时，同步更新文档。
- 后端路由、校验、设置持久化、UI 回归或发布脚本有变化时，补充聚焦测试。

### 本地检查

提交 PR 前建议运行：

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
npm audit --audit-level=moderate
node --check tauri-shell/src/main.js
cd tauri-shell/src-tauri && cargo check
```

安全相关变更建议额外运行：

```bash
uvx pip-audit --strict
```

### Pull Request

- 使用 PR 模板。
- 每个 PR 保持单一目的。
- UI 改动请附截图或简短录屏。
- 说明测试过的后端：本地 Ollama、自定义 Ollama 端口、OpenAI-compatible 云端，或两者都测。
- 不要提交密钥、个人签名证书、私有 API key、运行时数据库、日志、构建产物或安装包。
