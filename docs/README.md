# TeXada Docs / 文档索引

This directory keeps technical and maintenance documentation. Community health files live under `.github/` so GitHub can detect them without crowding the repository root. `README.md`, `LICENSE`, and `CHANGELOG.md` stay at the root because they are primary project entry points.

本目录保存技术与维护文档。社区健康文件放在 `.github/` 下，既方便 GitHub 识别，也避免根目录拥挤。`README.md`、`LICENSE` 和 `CHANGELOG.md` 保留在根目录，因为它们是项目主入口。

## Technical Docs / 技术文档

| Document | Purpose |
|----------|---------|
| [Why TeXada?](comparison.md) / [为什么选择 TeXada](comparison.md) | Product-focus comparison with links to the official documentation of adjacent tools. |
| [Design philosophy](design-philosophy.md) / [设计哲学](design-philosophy.md) | Why the planner decides, deterministic tools execute, and the compiler verifies. |
| [Design evolution](design-evolution.md) / [设计思路与版本迭代](design-evolution.md) | Long-form product, architecture, algorithm, and per-version Diff rationale from the original prototype through v0.3.8. |
| [Architecture](architecture.md) / [架构文档](architecture.md) | System layout, backend model flow, frontend shell, configuration, CI and release shape. |
| [Architecture freeze](architecture-freeze-v0.4.md) / [架构冻结](architecture-freeze-v0.4.md) | Frozen v0.4-v1.0 layers, milestone scope, and change gate. |
| [Iteration roadmap](iteration-roadmap-v0.4.1-to-v1.0.md) / [迭代路线图](iteration-roadmap-v0.4.1-to-v1.0.md) | Current authoritative sequencing: decisions D1-D7, iteration order and acceptance gates from v0.4.1 to v1.0, plus recorded milestone drift. |
| [ADR-011 Formula Runtime Ledger](adr/011-formula-runtime-ledger.md) | Revision-bound formula state, evidence lifecycle, and commit barrier decision. |
| [ADR-012 Planner Projection](adr/012-planner-projection.md) | Bounded model-facing state and Semantic summaries without full trees. |
| [ADR-013 Golden Set Evidence](adr/013-golden-set-evidence.md) | Cross-cutting evidence track: golden set, repair dataset, recorded vs real modes, CI boundary. |
| [ADR-014 Tool Runtime Contract](adr/014-tool-runtime-contract.md) | v0.4.1 tool-contract work merged into the v0.5 design phase; capability probe, schema validation, affordance policy. |
| [ADR-015 Semantic Patch Apply Model](adr/015-semantic-patch-apply-model.md) | Hybrid patch model: planner produces patches, deterministic applier applies, Scope Guard bounds, commit barrier decides. |
| [ADR-016 Local Model Runtime](adr/016-local-model-runtime-llama-server.md) | Built-in llama-server sidecar as default runtime with Ollama and cloud as compatibility backends. |
| [SymPy capability matrix](sympy-capability-matrix.md) / [SymPy 能力矩阵](sympy-capability-matrix.md) | Generated boundary declaration for the optional, unregistered CAS scaffold, including parser drift, deterministic seed policy, and acceptance red lines. |
| [Local E2E](e2e-manual.md) / [本地端到端测试](e2e-manual.md) | Human and automated validation for the MiniCPM5 Agent Runtime path. |
| [Local model comparison, 2026-09-12](local-model-benchmark-2026-09-12.md) / [本机模型对照](local-model-benchmark-2026-09-12.md) | MiniCPM5-1B/2B Q4 local measurements, development-regression scope, thinking tradeoffs, and deployment evidence; not an official installer release announcement. |
| [Data backup](data-backup.md) / [数据备份](data-backup.md) | JSON export/import format, history merge rules, preset handling, and API key safety. |
| [Technical report](technical-report.md) / [技术报告](technical-report.md) | v0.3.2 technical baseline with current model notes; historical measurements remain attributed to their original models. |
| [Source audit](audit.md) / [源码审计](audit.md) | Cleanup scope, removed stale paths, current release surface and intentional defaults. |
| [File inventory](file-inventory.md) / [文件清单](file-inventory.md) | Purpose of every tracked file that remains in the repository. |

## Design Docs / 设计文档

| Document | Purpose |
|----------|---------|
| [Golden set evidence I design](specs/2026-09-19-golden-set-evidence-i-design.md) / [证据闭环 I 设计](specs/2026-09-19-golden-set-evidence-i-design.md) | Iteration 1 design: golden set automation, repair dataset, recorded and real execution modes, acceptance gates. |
| [Golden set evidence I implementation plan](specs/2026-09-19-golden-set-evidence-i-plan.md) | Task-by-task implementation plan for the Iteration 1 golden set, including CI wiring and baseline reporting. |
| [Llama-server runtime design](specs/2026-09-19-llama-server-runtime-design.md) | Iteration 1.5 design: built-in llama-server sidecar, three-backend selection, in-app lifecycle and model pull. |
| [Llama-server runtime implementation plan](specs/2026-09-19-llama-server-runtime-plan.md) | Task-by-task implementation plan for the llama-server migration. |

## Community And Release / 社区与发布

| Document | Purpose |
|----------|---------|
| [README](../README.md) | User guide, installation package path, Ollama quick start, cloud mode and hardware notes. |
| [Recorded examples](../examples/README.md) | Short desktop runs for natural-language conversion, OCR, and deterministic repair. |
| [Contributing](../.github/CONTRIBUTING.md) | Contribution rules, validation checklist, and no hard-coded interface policy. |
| [Security](../.github/SECURITY.md) | Supported versions and private vulnerability reporting. |
| [Support](../.github/SUPPORT.md) | Bug-report checklist and model/Ollama troubleshooting entry point. |
| [Code of Conduct](../.github/CODE_OF_CONDUCT.md) | Community behavior expectations. |
| [Changelog](../CHANGELOG.md) | Release history. |
