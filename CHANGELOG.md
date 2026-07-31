# Changelog / 变更记录

All notable changes to TeXada-the-Math-Agent are recorded here.

## 0.3.4 - 2026-07-31

### English

- Fixed a macOS Hardened Runtime crash found by launching the notarized v0.3.3
  DMG through the real desktop GUI. The backend initially reported ready, but
  the first KaTeX request terminated the sidecar with
  `Failed to reserve virtual memory for CodeRange`; the UI then returned to
  `No API` and showed a network error.
- The packaged MiniRacer/V8 runtime requires executable-memory permissions
  when its entrypoint is signed with Developer ID and Hardened Runtime. The
  macOS sidecar entrypoint is now signed with
  `com.apple.security.cs.allow-jit` and
  `com.apple.security.cs.allow-unsigned-executable-memory`; all native
  libraries remain signed by the same Developer ID so library validation
  stays enabled.
- Added release gates that inspect the signed sidecar entitlements and execute
  a real zero-token `二重积分` Agent request against the signed frozen sidecar.
  The smoke test requires `valid=true`,
  `stop_reason=deterministic_candidate`, and the
  `katex-0.17.0-v8` parser backend before desktop packaging can continue.
- Reproduced the v0.3.3 failure from the official notarized DMG, then verified
  the entitlement fix in a Hardened Runtime copy through the real GUI:
  backend startup stayed online, `二重积分` and `分段函数` rendered as valid
  KaTeX, and all built-in preset formulas rendered successfully.

### 中文

- 修复通过真实桌面 GUI 启动 v0.3.3 已公证 DMG 时发现的 macOS Hardened
  Runtime 崩溃。后端最初会显示已就绪，但第一次 KaTeX 请求会令 sidecar 以
  `Failed to reserve virtual memory for CodeRange` 退出，随后界面回到
  `No API` 并显示网络错误。
- MiniRacer/V8 在 Developer ID 与 Hardened Runtime 签名下需要可执行内存权限。
  现在 macOS sidecar 入口会带
  `com.apple.security.cs.allow-jit` 和
  `com.apple.security.cs.allow-unsigned-executable-memory` 权限签名；所有
  原生库仍由同一 Developer ID 签名，因此不会关闭 library validation。
- 新增发布门禁：检查正式签名 sidecar 的 JIT 权限，并对签名后的冻结 sidecar
  执行真实的零 token“二重积分”Agent 请求。只有同时满足 `valid=true`、
  `stop_reason=deterministic_candidate` 和 `katex-0.17.0-v8` 解析后端，才允许
  继续桌面打包。
- 已从 v0.3.3 官方公证 DMG 复现该故障，并在 Hardened Runtime 修复副本上通过
  真实 GUI 验证：后端持续在线，“二重积分”和“分段函数”均生成有效 KaTeX，全部
  内置预设公式正常渲染。

## 0.3.3 - 2026-07-31

### English

- Fixed the Agent finalization regression introduced in v0.3.1. A candidate
  that remained invalid after deterministic repair was raised as a generic
  runtime exception, turning a recoverable validation result into HTTP 503 and
  discarding the formula, diagnostics, and Agent trace. The runtime now
  returns a structured `valid=false` result with
  `validation_failed_after_repair`, preserving observability and allowing the
  desktop UI to show the candidate and diagnostics.
- Fixed packaged KaTeX validation on macOS and Windows. PyInstaller previously
  copied the Python `py_mini_racer` module but omitted its native MiniRacer
  library and ICU data, so source-tree tests passed while the packaged
  sidecar reported `KaTeX parser unavailable`. Sidecar builds now collect the
  complete MiniRacer runtime.
- Fixed the desktop startup bridge. The frontend expected
  `window.__TAURI__.core.invoke`, while the Tauri bundle did not expose the
  global bridge; this made a running sidecar appear as `No API`. The bridge is
  now enabled, detected defensively, and retried for up to 60 seconds during
  backend startup.
- Fixed preset KaTeX cards in compact windows with bounded two-column sizing,
  non-overflowing cards, and horizontal scrolling for long formulas. Added an
  explicit Use action without removing LaTeX and Markdown copy actions.
- Added zero-token deterministic candidates for double integrals, triple
  integrals, and piecewise functions in Chinese and English. These common
  prompts still run through the real compile and render tools.
- Improved desktop reliability with configurable inference/request timeouts,
  OCR elapsed and retry states, history/run-log refresh and loading states,
  and keyboard/ARIA tab behavior.
- Verified the release with 263 passing tests and 11 optional skips, Ruff,
  JavaScript syntax checks, Rust `cargo check`, a signed local macOS arm64
  application build, and real desktop GUI checks. `二重积分` and `分段函数`
  both produced valid KaTeX with zero model tokens, and all built-in presets
  rendered in the corrected grid.

### 中文

- 修复 v0.3.1 引入的 Agent 收尾回归。候选公式在确定性修复后仍未通过验证时，旧逻辑
  会抛出通用运行时异常，把本可返回的验证结果变成 HTTP 503，并丢失公式、诊断和
  Agent 轨迹。现在会返回结构化的 `valid=false` 结果及
  `validation_failed_after_repair` 停止原因，桌面端和运行日志能够保留完整现场。
- 修复 macOS 与 Windows 打包版的 KaTeX 验证。PyInstaller 过去只收集了
  `py_mini_racer` Python 模块，没有带上原生 MiniRacer 动态库和 ICU 数据，导致
  源码环境测试正常、桌面 sidecar 却报告 `KaTeX parser unavailable`。现在 sidecar
  构建会完整收集 MiniRacer 运行时。
- 修复桌面启动桥接。前端依赖 `window.__TAURI__.core.invoke`，但 Tauri 包未暴露
  全局桥接，因此已经运行的 sidecar 仍会显示 `No API`。现在已启用桥接、增加稳健
  检测，并在后端启动阶段最多重试 60 秒。
- 修复紧凑窗口中的预设 KaTeX 卡片：双列宽度有界、卡片不再溢出，长公式可横向
  滚动；同时新增明确的“使用”操作，并保留 LaTeX 与 Markdown 复制。
- 为中英文“二重积分”“三重积分”和“分段函数”增加零 token 确定性候选；这些候选
  仍会经过真实的编译与渲染工具验证。
- 提升桌面可靠性：支持配置推理/请求超时，补充 OCR 计时与重试状态、历史和运行
  日志刷新/加载状态，以及键盘和 ARIA 标签页行为。
- 发版候选已通过 263 项测试（另有 11 项可选跳过）、Ruff、JavaScript 语法检查、
  Rust `cargo check`、本地签名的 macOS arm64 应用构建和真实桌面 GUI 测试。
  “二重积分”和“分段函数”均以零模型 token 生成有效 KaTeX，全部内置预设也在修正
  后的网格中正常渲染。

## 0.3.2 - 2026-07-28

### English

- Added an experimental, optional CAS capability boundary under
  `src/texada/cas/`. It is intentionally not registered in `TeXToolset`, the
  Agent Runtime, the API, or the desktop UI; this release does not advertise a
  general formula-correctness checker.
- Added a conservative `Semantic Unit → SymPy` whitelist translator for exact
  integers/rationals, scalar arithmetic, rational powers and roots, selected
  elementary functions, simple equations, and bounded definite integrals.
  Matrices, cases, sums/products, quantum notation, accents,
  `\operatorname`, ambiguous `e`/`i`, unknown commands, and fallback-parser
  documents are rejected before comparison.
- Added auditable CAS results with separate status, evidence basis, and
  evidence grade (`exact` or `symbolic_heuristic`), plus declared assumptions,
  exact finite witnesses, task seed, SymPy/policy versions, and a reproducible
  cache key.
- Hardened SymPy comparison policy: `.equals() == False` is observation only;
  exact difference requires finite exact counterevidence; non-finite,
  piecewise, unevaluated, or timed-out work returns `unknown`/`timeout`.
  Convergence checks are recorded as auxiliary evidence and never used alone
  to equate a divergent series with positive infinity.
- Added a reusable spawned worker process with per-task SymPy seed reset,
  deadline-triggered kill/restart, and parent-side PID RSS monitoring via
  `psutil`. The policy does not rely on macOS `RLIMIT_AS`.
- Added the pinned, machine-readable `eval/cas_capabilities.yaml` matrix for
  production adapter cases, ANTLR/Lark drift probes, SymPy contract probes,
  seed reproducibility, assumptions, resource boundaries, and the
  zero-false-verified acceptance gate.
- Added generated capability documentation and synchronization checks. SymPy,
  psutil, ANTLR, Lark, and PyYAML remain optional `cas`/`cas-eval`
  dependencies, so the default desktop sidecar and installer size are
  unchanged.
- Verified the release candidate with Ruff, `git diff --check`, 281 passing
  tests and 8 optional skips. The 35 focused CAS tests also passed five
  consecutive runs without a seed-dependent gate flip.

### 中文

- 在 `src/texada/cas/` 新增实验性、可选的 CAS 能力边界。它刻意没有注册进
  `TeXToolset`、Agent Runtime、API 或桌面 UI；本版本不宣称已经提供通用公式正确性
  检查器。
- 新增保守的 `Semantic Unit → SymPy` 白名单转换器，仅覆盖精确整数/有理数、标量
  四则运算、有理幂与根式、少量初等函数、简单方程和有界定积分。矩阵、cases、
  求和/乘积、量子记号、重音命令、`\operatorname`、有歧义的 `e`/`i`、未知命令
  以及 fallback parser 文档都会在进入比较器前明确拒绝。
- 新增可审计 CAS 结果：结论状态、证据 basis 与证据等级（`exact` 或
  `symbolic_heuristic`）相互分离，并携带 assumptions、有限精确反例、任务 seed、
  SymPy/policy 版本和可复现缓存键。
- 加固 SymPy 比较策略：`.equals() == False` 永远只作 observation；判定不同必须有
  有限精确反例；非有限、Piecewise、未求值或超时结果统一返回
  `unknown`/`timeout`。收敛性只作为辅助证据，不能单独把“不收敛”升级为“等于
  正无穷”。
- 新增可复用 spawn worker：每个任务重置 SymPy seed，超时后由父进程杀死并重建，
  并通过 `psutil` 按子进程 PID 轮询 RSS；策略不依赖 macOS `RLIMIT_AS`。
- 新增固定环境的机器可读能力矩阵 `eval/cas_capabilities.yaml`，覆盖生产 adapter、
  ANTLR/Lark 静默漂移、SymPy 契约、seed 可复现性、assumptions、资源边界，以及
  “错误 verified 为 0”的验收红线。
- 新增由能力矩阵生成的说明文档和同步检查。SymPy、psutil、ANTLR、Lark 与 PyYAML
  仍只属于可选的 `cas`/`cas-eval` 依赖，默认桌面 sidecar 与安装包体积不变。
- 发布候选已通过 Ruff、`git diff --check`、281 项自动化测试（另有 8 项可选跳过）；
  35 项 CAS 定向测试连续运行五轮全部通过，没有出现 seed 导致的门禁翻转。

## 0.3.1 - 2026-07-28

### English

- Added zero-model completion for bare superscripts/subscripts, empty arguments,
  empty bounds, and trailing operators using editable `\placeholder{}` slots.
- Added conservative local correction for uniquely matched common LaTeX command
  typos and deterministic repair for mismatched environments.
- Added canonical zero-model candidates for explicit named concepts found during
  the 200 NL + 200 completion desktop audit.
- Hardened the Agent Runtime so non-candidate tools cannot replace formula state,
  intent-aware fallback replaces the old generic fallback, invalid formulas
  cannot render or finalize, and leaked prompt labels are removed from tool args.
- Fixed Agent execution trace layout by placing the candidate origin and tool
  badges on separate rows, preventing `deterministic_candidate`,
  `compile_tex`, and `render_math` from overlapping in compact windows.
- Audited 200 NL and 200 completion cases through the real desktop UI. The
  resulting targeted 59-case regression passes 59/59 with zero model tokens,
  averaging 8.73 ms and peaking at 261.08 ms.
- Verified the release candidate with 246 passing tests, 8 optional skips,
  lockfile validation, Rust checks, a macOS application build, and installed-app
  Computer Use checks for superscripts, subscripts, and expanded traces.

### 中文

- 为裸上标/下标、空参数、空上下界和尾部运算符新增零模型补全，使用可继续编辑的
  `\placeholder{}` 占位槽，不再让小模型猜测缺失内容。
- 为唯一匹配的常见 LaTeX 命令拼写错误加入保守本地纠错，并支持环境不匹配的确定性
  修复。
- 根据 200 条 NL 与 200 条补全桌面审计结果，为明确命名的数学概念新增零模型标准
  候选。
- 加固 Agent Runtime：非候选工具不能覆盖公式状态；兼容回退会保留真实意图；无效
  公式不能渲染或作为成功结果返回；工具参数中的提示词标签会被清理。
- 执行轨迹改为两行布局：第一行显示 `deterministic_candidate` 等来源与状态，第二行
  单独显示 `compile_tex`、`render_math` 工具标签，彻底修复紧凑窗口中的文字重叠。
- 通过真实桌面 UI 完成 200 条 NL 与 200 条补全审计；针对发现问题建立的 59 条回归
  用例全部通过，模型 token 为 0，平均耗时 8.73 ms，最大耗时 261.08 ms。
- 发布候选已通过 246 项自动化测试（另有 8 项可选跳过）、锁文件校验、Rust 检查、
  macOS 应用构建，以及安装版 Computer Use 上下标和执行轨迹检查。

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
