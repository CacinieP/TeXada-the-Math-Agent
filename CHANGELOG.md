# Changelog / 变更记录

All notable changes to TeXada-the-Math-Agent are recorded here.

## 0.3.0 - 2026-07-27

- Repositioned TeXada as an on-device, agent-driven structured math editor.
- Added a MiniCPM5 Planner → Tool → Observation runtime with native XML and
  OpenAI tool-call normalization.
- Added independent `parse_tex`, `compile_tex`, `repair_tex`, `semantic_diff`,
  `render_math`, and `export` tools.
- Added a pinned KaTeX 0.17.0 AST bridge in reusable in-process V8, normalized
  semantic units, and role-aware weighted tree-edit observations/rewards.
- Preserved the original SymbolEngine/operator-drift guard as Level 0, shared
  it with the Agent Runtime, and added bounded retry/error/duplicate-call
  circuit breakers.
- Kept `repair_tex` as a deterministic local syntax tool; TeXada now has only
  two model roles: MiniCPM5-1B for planning/text and MiniCPM-V 4.6 for OCR.
- Switched the desktop NL path to `/api/agent` and added a visible execution
  trace for local E2E testing.
- Routed OCR and completion candidates through the same MiniCPM5 Agent Runtime;
  all three product inputs now expose candidate intake, tool observations,
  semantic state, stop reason, and visible execution traces.
- Added OCR fallback extraction from vision reasoning fields, one bounded empty
  response retry, and an actionable service error instead of an uncaught
  empty-candidate failure.
- Added a CC Switch-inspired request ledger with unique run IDs, indexed
  filters, success/error symmetry, Agent trace detail, and history correlation.
- Added schema-v2 full backups and independent JSON import/export for run logs,
  result history, and custom presets.
- Added a deterministic integral-structure fast path for SymbolEngine-anchored
  rank/domain phrases, reducing the real double-integral E2E from about 106
  seconds to about 4.8 seconds and preventing prose such as `in region D` from
  leaking into syntactically valid formulas.
- Added zero-token deterministic candidates for high-confidence range sums,
  quotient limits, partial derivatives, multiple integrals, fractions, simple
  arithmetic, grouped powers, radicals, and explicit inline LaTeX hints.
- Added instant completion rules for common command prefixes and safely
  repairable partial formulas while preserving compile/render tool observations.
- Normalized common MiniCPM escaping artifacts in OCR candidates and made
  structured Chinese input tolerant of sentence punctuation and natural
  synonyms such as “加上”, “乘以”, and “趋近于”.
- Changed run-log lists to paginated lightweight summaries with lazy trace
  detail, separate request/formula status badges, and unlimited default
  retention with opt-in caps.
- Migrated cursor-relative window positioning to Tauri's monitor APIs, added
  `httpx2` for tests, and updated Pillow to 12.3.0.

## 0.3.0 - 2026-07-27 中文

- 将 TeXada 重新定位为基于端侧 Agent 的结构化数学编辑器。
- 新增 MiniCPM5 Planner → Tool → Observation 运行时，同时兼容原生 XML 与
  OpenAI `tool_calls`。
- 新增六个职责单一的 TeX 工具：解析、编译校验、修复、语义 Diff、渲染与导出。
- 新增固定 KaTeX 0.17.0 的进程内 V8 AST 桥、归一化 Semantic Unit，以及角色感知
  的加权树编辑 Observation/Reward。
- 保留原有 SymbolEngine/算符漂移守卫作为 Level 0，由 Agent Runtime 共享，并新增
  有界重试、连续错误与重复工具调用熔断。
- `repair_tex` 明确保持为确定性本地语法工具；TeXada 现在只有两个模型角色：
  MiniCPM5-1B 负责规划/文本，MiniCPM-V 4.6 负责 OCR。
- 桌面 NL 主路径切换到 `/api/agent`，并加入可展开的执行轨迹，便于本地 E2E。
- OCR 与补全候选也统一进入 MiniCPM5 Agent Runtime；三个产品入口现在都会返回
  candidate intake、工具 Observation、语义状态、停止原因与可见执行轨迹。
- OCR 现在会从视觉模型 reasoning 字段回退提取公式，并对空输出进行一次有界重试；
  若仍为空会返回明确服务错误，不再触发未捕获的空候选异常。
- 新增参考 CC Switch 请求账本思想的运行日志：唯一 run ID、索引筛选、成功/失败
  对称记录、Agent trace 详情，以及与结果历史关联。
- 完整备份升级为 schema v2，并支持运行日志、结果历史、自定义预设独立 JSON
  导入导出。
- 为 SymbolEngine 已锁定的积分阶数与积分域加入确定性结构快速路径：真实二重积分
  E2E 从约 106 秒降至约 4.8 秒，并阻止 `in region D` 等自然语言泄漏进语法合法
  但结构错误的公式。
- 为高置信度的区间求和、商式极限、偏导、多重积分、分式、简单运算、组合幂、
  根式和显式行内 LaTeX 增加零 token 确定性候选。
- 为常见 LaTeX 命令前缀和可安全修复的残缺公式增加即时补全规则，同时保留
  compile/render 工具 Observation。
- 归一化 OCR 候选中常见的 MiniCPM 转义伪影，并让结构化中文输入兼容句末标点
  以及“加上”“乘以”“趋近于”等自然同义表达。
- 运行日志改为分页轻量摘要、展开后按需加载 trace，分别显示请求状态与公式有效性；
  默认不限量保留，也可显式配置上限。
- 窗口跟随光标改用 Tauri 原生显示器 API；测试依赖加入 `httpx2`，Pillow 更新至
  12.3.0。

## 0.2.6 - 2026-07-20

- Added Settings -> Data controls for full backup export/import, history export/import, and confirmed history clearing.
- Added JSON backup APIs for full data export/import and history-only export/import.
- Added merge-mode history import with duplicate skipping and replace-mode support in the backend.
- Exported user-defined presets and non-sensitive settings while excluding API keys from backups.
- Documented the backup JSON format in README and `docs/data-backup.md`.
- Fixed platform-specific OCR paste hints so Windows shows `Ctrl+V` and macOS shows `Cmd+V`.

## 0.2.6 - 2026-07-20 中文

- 在设置页新增“数据”区域，支持完整备份导入导出、历史记录导入导出，以及二次确认后清空历史。
- 新增完整数据和仅历史记录的 JSON 导入导出 API。
- 后端历史导入支持合并模式去重，并保留替换模式能力。
- 备份会导出用户自定义预设和非敏感设置，但不会导出 API Key。
- 在 README 和 `docs/data-backup.md` 中补充备份 JSON 格式说明。
- 修正 OCR 粘贴提示：Windows 显示 `Ctrl+V`，macOS 显示 `Cmd+V`。

## 0.2.5 - 2026-07-09

- Fixed the OCR tab so a second recognition can start immediately by dragging, pasting, or selecting another image after a completed run.
- Prevented duplicate OCR drag/drop handlers from being registered when reopening the OCR tab.
- Changed the desktop shell to open visible by default instead of starting hidden.
- Smoothed the frameless transparent window border by insetting and clipping the rounded shell on macOS and Windows.
- Stabilized macOS Intel release packaging by signing the bundled backend after PyInstaller creates it.

## 0.2.5 - 2026-07-09 中文

- 修复 OCR 页：第一次识别完成后，可以直接拖图、粘贴或选择另一张图片继续第二次识别。
- 避免反复进入 OCR 页时重复注册拖放事件，导致一次拖图触发多次请求。
- 桌面壳打开时默认显示窗口，不再默认隐藏。
- 通过透明 inset 和圆角裁剪修复 macOS、Windows 无边框透明窗口的边角瑕疵。
- 调整 macOS Intel 发布打包流程，PyInstaller 生成后再统一签名内置后端。

## 0.2.4 - 2026-07-08

- Fixed history result restoration: clicking a history record now reopens the previous generated formula in the result view without rerunning the model.
- Kept history input reuse as a separate action, while LaTeX and Markdown copy actions continue to copy the saved generated formula.

## 0.2.4 - 2026-07-08 中文

- 修复历史结果恢复：点击历史记录时会直接打开以前生成的公式结果，不需要重新跑模型。
- 保留“复用输入”为独立操作，同时 LaTeX 和 Markdown 复制按钮继续复制已保存的生成公式。

## 0.2.3 - 2026-07-08

- Replaced the app icon with a unified deep-blue no-star TeXada artwork.
- Regenerated the packaged macOS, Windows and frontend icon assets from the new artwork.
- Rethemed the desktop shell with layered deep-blue surfaces, controls, borders and focus states.

## 0.2.3 - 2026-07-08 中文

- 将应用图标替换为统一深蓝、无星标的 TeXada 新图。
- 基于新图重新生成 macOS、Windows 和前端打包图标资源。
- 将桌面壳 UI 调整为更有层次的深蓝界面，包括表面、控件、边框和聚焦态。

## 0.2.2 - 2026-07-08

- Renamed the shortcuts tab to Presets and made it a self-contained preset formula panel.
- Changed preset cards to insert formulas directly at the cursor instead of sending their keys through natural-language conversion.
- Added per-preset LaTeX and Markdown copy actions plus inline KaTeX previews.
- Treated optional local KaTeX CLI timeouts as skipped validation checks, matching missing CLI behavior.

## 0.2.2 - 2026-07-08 中文

- 将缩写页改为预设页，作为独立的预设公式面板使用。
- 预设卡片点击后直接在光标处键入公式，不再把 key 传入自然语言转换。
- 每个预设新增 LaTeX、Markdown 复制操作和内联 KaTeX 预览。
- 本地 KaTeX CLI 超时时按可选校验跳过处理，与 CLI 缺失时保持一致。

## 0.2.1 - 2026-07-08

- Fixed packaged desktop formula rendering when `npx katex` is unavailable.
- Bundled local KaTeX browser CSS, JavaScript, fonts, and license with the Tauri frontend.
- Changed backend KaTeX rendering to use `npx --no-install` and return a visible formula fallback instead of a user-facing `npx katex not available` error.
- Rendered OCR and completion results with the same local KaTeX frontend path.

## 0.2.1 - 2026-07-08 中文

- 修复桌面安装包中缺少 `npx katex` 时公式渲染版不可见的问题。
- 将本地 KaTeX 浏览器 CSS、JavaScript、字体和 license 随 Tauri 前端一起打包。
- 后端 KaTeX 渲染改用 `npx --no-install`，并在不可用时返回可见公式 fallback，而不是显示 `npx katex not available`。
- OCR 和补全结果也使用同一套前端本地 KaTeX 渲染路径。

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
