# TeXada Docs / 文档索引

This directory keeps technical and maintenance documentation. Community health files live under `.github/` so GitHub can detect them without crowding the repository root. `README.md`, `LICENSE`, and `CHANGELOG.md` stay at the root because they are primary project entry points.

本目录保存技术与维护文档。社区健康文件放在 `.github/` 下，既方便 GitHub 识别，也避免根目录拥挤。`README.md`、`LICENSE` 和 `CHANGELOG.md` 保留在根目录，因为它们是项目主入口。

## Technical Docs / 技术文档

| Document | Purpose |
|----------|---------|
| [Design evolution](design-evolution.md) / [设计思路与版本迭代](design-evolution.md) | Long-form product, architecture, algorithm, and per-version Diff rationale from the original prototype through v0.3.0. |
| [Architecture](architecture.md) / [架构文档](architecture.md) | System layout, backend model flow, frontend shell, configuration, CI and release shape. |
| [Local E2E](e2e-manual.md) / [本地端到端测试](e2e-manual.md) | Human and automated validation for the MiniCPM5 Agent Runtime path. |
| [Data backup](data-backup.md) / [数据备份](data-backup.md) | JSON export/import format, history merge rules, preset handling, and API key safety. |
| [Technical report](technical-report.md) / [技术报告](technical-report.md) | Model choice, deterministic pipeline, performance measurements, limitations and future direction. |
| [Source audit](audit.md) / [源码审计](audit.md) | Cleanup scope, removed stale paths, current release surface and intentional defaults. |
| [File inventory](file-inventory.md) / [文件清单](file-inventory.md) | Purpose of every tracked file that remains in the repository. |

## Community And Release / 社区与发布

| Document | Purpose |
|----------|---------|
| [README](../README.md) | User guide, installation package path, Ollama quick start, cloud mode and hardware notes. |
| [Contributing](../.github/CONTRIBUTING.md) | Contribution rules, validation checklist, and no hard-coded interface policy. |
| [Security](../.github/SECURITY.md) | Supported versions and private vulnerability reporting. |
| [Support](../.github/SUPPORT.md) | Bug-report checklist and model/Ollama troubleshooting entry point. |
| [Code of Conduct](../.github/CODE_OF_CONDUCT.md) | Community behavior expectations. |
| [Changelog](../CHANGELOG.md) | Release history. |
