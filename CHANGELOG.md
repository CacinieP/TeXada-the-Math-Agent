# Changelog / 变更记录

All notable changes to TeXada-the-Math-Agent are recorded here.

## 0.2.0 - 2026-07-08

- Improved history reuse with searchable natural-language, completion, OCR, and LaTeX records.
- Added history type filters and per-record actions for reusing source input, copying LaTeX, and copying Markdown.
- Extended the history API with `type` filtering and broader query matching across input, LaTeX, intent, and source fields.
- Enforced configured history retention by both age and maximum item count.

## 0.2.0 - 2026-07-08 中文

- 增强历史记录复用：可搜索自然语言、补全、OCR 和 LaTeX 记录。
- 历史页新增类型筛选，以及复用输入、复制 LaTeX、复制 Markdown 等单条记录操作。
- 扩展历史 API，支持 `type` 筛选，并在输入、LaTeX、intent 和 source 字段中检索。
- 历史记录清理同时遵守保留天数和最大条数配置。

## 0.1.0 - 2026-07-07

- Released the Tauri desktop app surface for macOS DMG and Windows NSIS installers.
- Added local-first Ollama MiniCPM defaults with configurable text and vision models.
- Added OpenAI-compatible cloud mode with separate text and vision model settings.
- Added natural language conversion, OCR, completion, snippets, history, validation, repair, rendering, copy, and insert-at-cursor flows.
- Added bilingual README, architecture notes, source audit, technical report, release workflows, and community health files.

## 0.1.0 - 2026-07-07 中文

- 发布 Tauri 桌面应用，支持 macOS DMG 和 Windows NSIS 安装包。
- 默认使用本地 Ollama MiniCPM，并支持配置文本模型和视觉模型。
- 支持 OpenAI-compatible 云侧模式，可分别设置文本模型、视觉模型和 endpoint。
- 支持自然语言转 LaTeX、OCR、补全、缩写、历史、校验、修复、渲染、复制和光标处键入。
- 补齐中英双语 README、架构文档、源码审计、技术报告、release workflow 和社区健康文件。
