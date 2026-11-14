# Changelog / 变更记录

## Unreleased

- 首次启动按系统语言选择界面，中文环境默认中文，其余环境默认英文。已保存的语言偏好优先，调整缩放不会固定自动选择的语言。
- Choose the first-run UI language from the system locale and fall back to English. Preserve saved language preferences independently of zoom.

## 0.4.9 - 2026-11-13

- 新增术语名词表 `src/texada/core/glossary.py`（24 条，含格林/高斯/斯托克斯/贝叶斯/全概率/华里士/施密特/拉格朗日/罗尔/柯西/泰勒/洛必达/一阶线性 ODE/二阶常系数/中心极限/样本方差/欧拉/夹逼/路径无关/二项分布/分部积分/N-L/柯西不等式/秩不等式），每条带名称别名、LaTeX、出处与备注。
- 词表沿既有确定性快路径接入：`DeterministicCandidateEngine._canonical_concept` 兜底查表（规则名仍为 `nl_canonical_concept`），`/api/convert` 在同一处先查表，命中返回 `Source.TEMPLATE`、`tokens_used=0`。匹配要求规范化后与别名完全相等，带参数的句子与复合问句仍交给模型；每条 LaTeX 必须通过 KaTeX 校验，失败则回退模型路径。
- 实测（MiniCPM-V 4.7 1B）：真实语料 31/52 → **47/52**，其中 `named-formula` 5/20 → **20/20**；52 条里 21 条零 token 直出，词表命中 p50 ≈ 12 ms，模型路径 ≈ 0.8 s。100 条 golden set 仍为 59/95，未借词表刷分。
- 评测 runner 现在区分「确定性直出」与「模型结果」并单列条目，避免把查表得分读成模型能力；README 中英双段与 `docs/architecture.md`、`eval/known-gaps.md`（G-017）同步。
- Serve bare theorem names from a curated glossary (24 entries) on the existing deterministic-candidate path, so the small model is no longer asked to recall textbook formulas.

## 0.4.8 - 2026-11-13

- 修复计算范围门禁的误拒：`u 除以 v 的求导法则`、`泰勒公式的求导法则`、`基本积分公式表` 这类"要排版的内容"此前因动词 `求导` 命中而被整句拒绝。现在动词扫描前先剥离 `求导/积分/极限 +（的）法则|公式|规则|表` 固定搭配，`计算这个求导公式`、`推导…的求导法则` 仍按计算请求拒绝。
- 基线报告把范围拒绝与失败分开统计。`ComputationOutsideScope` 不再计入 Errors 与分母，改为单列条目（当前为 golden `010`、`073`）；两条已登记为有意的产品边界（`eval/known-gaps.md` G-016）：`010` 要的是因式分解结果，`073` 无法用正则与真实求导请求区分。
- 复测 100 条 golden set（MiniCPM-V 4.7 1B，内置 llama-server）：结构通过 59/95（62.1%）、编译 92/100、渲染 98/100、轨迹 98/100、确定性修复 53/53；延迟 p50/p95 = 1.5s/4.2s。分母由 94 变 95 是因为 `062` 重新进入评测，不代表通过率下降。
- Treat nominalised `求导法则/公式/表` phrases as content to typeset rather than computation requests, and report scope-gate refusals separately from failures in the baseline.

## 0.4.7 - 2026-11-13

- 修复拼错命令与非法环境名没有任何自动修复路径的问题。KaTeX 成为唯一语法权威后只产出 `katex_parse` 错误，而 fixer 只处理旧的三类错误；现在 `Undefined control sequence: \X` 走截断命令白名单（`\fr`→`\frac`、`\bet`→`\beta` 等，只在完整命令边界替换），`No such environment: X` 走唯一前缀映射（`case`→`cases`，多候选拒绝猜测）。确定性修复改为最多三轮且可组合（改环境名 + 补 `\end`），每轮重新校验，最终仍非法则保留原答案。
- 补齐“只转写不解答”的两段缺口。输入侧 `scope` 增补口语化求值说法（`等于几`、`是几`、`是多少`、`加到 N 的和`），这些真实用例此前会绕过门禁；输出侧新增求值守卫，检出“等号右边是用户从未写过的常数”时带 `transcribe_only` 约束重试一次，重试仍求值则保留首个答案并写 `fix_log=["evaluation-suspected"]`，不静默替换为另一个错答案。
- 新增真实语料评测集 `eval/real_world_set.yaml`（52 条）与判定器 `eval/real_world_lib.py`、在线基线运行器 `eval/run_real_world.py`、`tests/test_real_world_set.py`（225 条离线断言）。语料覆盖术语名、讲义/真题整句、易混清单、只转写不解答与半截 LaTeX 补全，逐条可溯源；`docs/test-prompts-real-world.md` 为同步的人读表格，`eval/known-gaps.md` 增补 G-009…G-014。
- 基线（`minicpm-v4.7-1b`，llama-server，52 条）：通过 31 条；`no-solving` 6/6（由输入侧门禁拒绝）、`completion` 10/11、`lecture-sentence` 6/8、`common-mistake` 4/7、`named-formula` 5/20。本轮不宣称模型质量结论，明细见 `eval/real-world-baseline.json`。
- `ConversationMemory` 明确标注为“只记录、不喂给模型”，两处写入点加注释与回归测试指引，避免后续维护者误当上下文丢失的 bug 修回去。
- Fix silent repair gaps for mistyped commands and illegal environment names, add an output-side evaluation guard, and ship a 52-entry real-world corpus with an offline judge and live baseline runner.

## 0.4.6 - 2026-11-10

- Fix Linux compatibility by building the desktop, Python backend and pinned llama-server on Ubuntu 22.04 / glibc 2.35.
- Reject packaged ELF imports newer than glibc 2.35, including weak imports. Validate deb installation and extracted AppImage startup with external networking disabled and loopback retained.
- Linux validation covers desktop/backend startup and deterministic KaTeX rendering; it does not test model inference, every Linux distribution, or AppImageHub acceptance.
- Preserve published v0.4.5 assets. Version 0.4.6 requires freshly built installers, matching SHA-256 checksums and source-bound validation reports.
- 修复 Linux 构建基线和离线启动验证；保留 v0.4.5 原始发布文件，新版使用独立版本与校验记录。

## 0.4.5 - 2026-11-08

- Clear stale history previews and their action closures on close, refresh/filter and successful history deletion without stealing search-field focus. / 关闭、刷新/筛选及成功清空历史时同步清理旧预览和操作引用，避免残留已移除内容或抢走搜索输入焦点。

- 修复历史矩阵/预设卡片渲染：KaTeX 每次使用独立可变宏表，避免冻结宏表在矩阵环境中抛错；保留宏隔离及可见的源码回退。历史「查看」改为页内只读数学预览，不再自动跳到预设或覆盖草稿；只有「复用输入」才恢复参数。大矩阵首尾列均可滚动查看。见 [#70](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/70)。
- Fix matrix/preset rendering with per-render mutable macro copies. View historical formulas in a read-only History preview without navigating or changing drafts; only explicit reuse restores editor parameters. Preserve full source, visible render failures, and scrollable edges for wide matrices. [Validation](docs/issue70-history-preview.md).

## 0.4.4 - 2026-11-06

### 中文

- macOS 插入前先隐藏窗口和应用，隐藏失败时返回错误并停止发送粘贴命令。托盘、快捷键和显示命令恢复应用后显示并聚焦窗口。新增无公式正文的插入阶段诊断，目标应用实际收文与恢复流程继续由 #64 原生验收。
- 矩阵预设增加单位、零、对角、上三角和下三角矩阵，支持按类型搜索、具体与符号尺寸、括号和索引起点。新类型共用矩阵生成、修订绑定结构检查、历史恢复及备份链路。
- 修复有限求和描述的求和项、整数索引域和区域积分保真问题。未指定范围或积分测度时保留一般记号，缺失或冲突索引时显示补充提示。实际候选通过当前 revision 的结构检查后提交。带上下文的请求进入规划并记录未检查范围，正式版 v0.4.3 的三条失败输出固化为回归。
- 将正式版 v0.4.3 的 C10/C11/C12 原始矩阵失败输出固化为带版本来源的最小公式样例。离线回归验证语法有效、需求判定 `DIFFERENT`、当前提交屏障拒绝，以及修正候选 `MATCH`。
- 修复矩阵评审发现的四项问题，矩阵专用工具采用 32768 字符预算，大公式可校验并往返导入历史与日志。带补充上下文的请求进入规划，候选生成同时读取上下文。矩阵历史按参数恢复预设，兼容旧版自然语言记录。维度解析保留前导小数点。
- 预设页新增参数化通用矩阵与三对角矩阵，支持具体/符号尺寸、上下对角、括号、索引起点及展开方式。有限自然语言矩阵句式复用同一生成逻辑，受支持模式零模型调用。
- 新增 `POST /api/matrix`，复用现有 Agent 结果、历史与运行日志。矩阵候选经过编译、渲染及绑定当前 revision 的结构检查，需求不匹配或检查不受支持时保留诊断并阻止提交。
- 增加旧式自定义预设与备份导入的兼容性回归。矩阵表单编辑后清理过期结果，结构判定和复制/插入状态分别显示。

- 同步 0.4.4 版本、下载入口和发行说明，正式安装产物与原生验收范围按本次发布附件记录。[发布说明](docs/release-v0.4.4.md)

### English

- Hide both the window and macOS application before insertion, propagate hide failures, and restore the application before showing/focusing its window. Add content-free insertion-stage diagnostics. Native target-text and restoration acceptance is tracked in #64.
- Add identity, zero, diagonal, upper-triangular and lower-triangular matrix presets with type search, concrete or symbolic dimensions, brackets and index origin. New kinds share matrix generation, revision-bound checks, history restoration and backup replay.
- Preserve terms, integer domains and indexed region integrals in finite sum descriptions. Keep unspecified bounds and measures implicit, show clarification for missing or conflicting indices, and bind actual-candidate checks to committed revisions. Contextual requests enter planning with unchecked coverage recorded. Retain three exact v0.4.3 failures as regressions.
- Retain the exact C10/C11/C12 matrix failures from official v0.4.3 as minimal versioned formula fixtures. Offline regressions check valid syntax, `DIFFERENT` request evidence, rejection at the current Commit Barrier, and corrected `MATCH` candidates.
- Address the four matrix review findings with a bounded 32768-character matrix tool budget and large-formula validation/backup roundtrips, context-aware planning and candidate generation, parameter restoration for current and legacy matrix history, and preserved leading decimal points during dimension recognition.
- Add parameterized general and tridiagonal matrices to Presets with concrete or symbolic dimensions, diagonal expressions, brackets, index origin, and expanded or compact display. Supported natural-language descriptions share the zero-model generator.
- Add `POST /api/matrix` using the Agent response, history, and run ledger. Revision-bound matrix checks inspect the actual candidate alongside compilation and rendering, with diagnostics and commit blocking for mismatched or unsupported structures.
- Cover legacy custom-preset and backup imports in compatibility regressions. Form edits invalidate stale matrix results, and the result reports structure evidence and copy/insertion availability.
- Synchronize 0.4.4 metadata, download links and release notes, with tagged package identity and native acceptance scope recorded in the release assets. [Release notes](docs/release-v0.4.4.md)

## 0.4.3 - 2026-11-04

### 中文

- 修复主窗口关闭行为：阻止窗口销毁并改为隐藏，可通过托盘或现有快捷键恢复；显式 Quit 仍退出应用。增加关闭、退出码及本应用持有后端的生命周期日志，不记录公式或凭据。见 [PR #51](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/51)。
- 模型下载遇到传输中断或短响应时保留已接收片段，下一次通过 Range 续传；最终文件仍必须通过固定 SHA256，非法范围、超长响应与错误摘要继续拒绝。
- 整批下载增加明确的成功/失败结束事件；UI 不再把连接结束或单文件完成误报为全部成功。修复全缓存状态、重复点击并发、重试后的按钮恢复、流释放，以及每文件速度、剩余时间和中英文进度参数。
- 增加真实 HTTPX 中断/续传、完整性和取消回归、WHATWG ReadableStream 下载 UI 回归，以及 macOS/Windows 关闭策略检查。最终安装包验证以本标签的产物及报告为准；原生关闭/恢复/退出和连续 GUI 冷下载仍在 [#50](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50) 跟踪，历史退出触发原因未确认。
- 同步 0.4.3 版本、下载入口及[发布说明](docs/release-v0.4.3.md)。本版沿用原模型与公式策略，v0.4.2 的失败记录和模型质量结论不重新计分；编译、渲染及提交不代表数学正确。完整差异见 [v0.4.2…v0.4.3](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.2...v0.4.3)。

### English

- Hide the main window on close instead of destroying it; restore it through the tray or existing shortcut. Explicit Quit remains available. Add window, exit-code and owned-backend lifecycle logs without formula input or credentials. See [PR #51](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/51).
- Preserve the received model prefix after transport interruptions or short responses for the next Range retry. Final files still require the pinned SHA256; invalid ranges, overlong responses and bad hashes remain rejected.
- Add an explicit success/failure terminal for each download batch. Do not treat EOF or one finished file as overall success. Fix cached completion, duplicate streams, retry/button cleanup, reader release, per-file rate/ETA baselines and translated progress parameters.
- Cover real HTTPX interruption/resume, integrity and cancellation, WHATWG ReadableStream download UI behavior, and macOS/Windows close-policy regressions. Final package checks belong to this tag's artifacts and reports. Native close/restore/Quit and continuous GUI cold-download acceptance remain tracked in [#50](https://github.com/CacinieP/TeXada-the-Math-Agent/issues/50); the historical exit trigger is unknown.
- Synchronize 0.4.3 metadata, download links and [release notes](docs/release-v0.4.3.md). Models and formula policy remain unchanged; do not rescore v0.4.2 failures or infer mathematical accuracy from compilation, rendering or commits. [Full v0.4.2…v0.4.3 diff](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.2...v0.4.3).

## 0.4.2 - 2026-11-04

### 中文

- 正式整合 v0.4.1 以来已合并的 Beta/RC 与安全修复，发布 macOS Apple Silicon/Intel DMG、Windows x64 NSIS、Linux x64 deb/AppImage。版本元数据统一为 0.4.2；模型权重仍在安装后单独下载。发布范围与安装记录见[正式版说明](docs/release-v0.4.2.md)，最终安装包以标签构建的资产和验证记录为准。
- 保留 rc.3 的直接提交行为：自然语言、OCR、补全候选经过共享工具检查后直接进入结果与历史，复制/插入无需逐条采用。修改范围守卫仍会阻止越界提交；Studio 单公式移交继续走绑定的 pending review。产品用于公式识别、转写、编辑与排版，不求值、不解题。
- 内置 llama-server b11669，MiniCPM-V-4.7-1B Q4_K_M 与 F16 projector 按固定来源下载并在启动前校验 SHA256；修复打包运行时路径、模型/投影文件缺失及下载并发，加入断点续传、进度百分比、大小、速度和剩余时间。仅停止本应用持有的进程；模型注册与实际推理就绪分别显示。
- 设置页按内置、Ollama、OpenAI-compatible 后端显示对应字段；文本/OCR 连接和凭据分别保存，不向独立 OCR 地址自动转发文本密钥。保留未保存草稿、已有模型选择与用户设置；Ollama 4.7 思考控制修复和 1B 候选优先默认一并整合。
- 整合显式算符与操作数保护、版本绑定、过期结果丢弃、导出格式错误的一次有界恢复，以及设置标签布局与历史/运行日志。实验性行内补全提供光标绑定的零模型 insert-only Ghost Text，Tab 接受、Esc 忽略，旧响应不会重写光标两侧内容。
- 修复窄句式下标“加一”的漏项保护、合法一阶导数记法误拒绝和不等号严格结构识别。独立数据目录读取自己的连接设置。公式引擎的创建、调用和释放统一归属专用线程，关闭完成后才能重建，修复 Linux 回归发现的 V8 退出崩溃。
- 包含 [PR #45](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/45) 安全修复：Pillow 13.0.0、certifi 2026.10.23、setuptools 84.2.1、rustls 0.23.46 / webpki 0.103.16、离线 KaTeX 0.18.2；前后端使用同一 KaTeX。GTK3 所需的 glib 0.18.5 使用有来源的上游两行安全回移，不伪造为官方修复版、不忽略告警。Python/Rust 构建使用锁文件，npm 审计覆盖低危；发布前运行 Linux glib 优化迭代器回归。
- 正式版支持范围为公式识别、转写、编辑与排版，沿用当前直接提交策略。历史失败、结构差异及评测保持原样，独立人工转写复核、真实扫描/手写、目标平台模型质量仍是后续工作。编译、渲染、提交成功和安装启动不等于数学准确率；Linux 兼容性以最终 Ubuntu 原生安装检查为准。

### English

- Consolidate the merged beta/RC work since v0.4.1 and the security maintenance into v0.4.2. Ship macOS Apple Silicon/Intel DMGs, Windows x64 NSIS, and Linux x64 deb/AppImage packages with synchronized version metadata. Model weights download separately. See the [release scope and package records](docs/release-v0.4.2.md); final results belong to the tagged artifacts.
- Retain rc.3 direct commit for NL, OCR and completion: checked candidates appear in results/history and can be copied or inserted without an adoption click. Mutation-scope violations still block commits; Studio formula handoffs retain bound pending review. Product scope is formula recognition, transcription, editing and typesetting, not evaluation or solving.
- Bundle llama-server b11669 and verify pinned Q4_K_M/model-projector SHA256 before startup. Include runtime-path and download-concurrency fixes, resumable downloads, size/speed/ETA progress, owned-process cleanup and separate model-registration/inference-readiness states.
- Keep provider-specific settings, isolated text/OCR endpoints and credentials, preserved drafts and saved model choices, Ollama 4.7 thinking controls, and the usable 1B candidate-first default. Include source/revision guards, bounded recovery from invalid export formats, settings-tab fixes and observable history/run logs.
- Add experimental cursor-bound insert-only inline completion with zero model calls: ghost text, undoable Tab acceptance, Esc dismissal and stale-response rejection. Source text on either side of the cursor is retained.
- Preserve all terms in the narrow subscript-plus-one request, accept supported first-derivative notation, and cover the pinned not-equal AST. Isolated data directories load their own settings. Keep V8 creation, calls and cleanup on one owner thread and serialize close/reopen, fixing the native shutdown crash exposed by Linux regression.
- Include [PR #45](https://github.com/CacinieP/TeXada-the-Math-Agent/pull/45): patched Python locks, rustls/webpki and offline KaTeX 0.18.2, plus the documented upstream two-line glib 0.18.5 source backport required by GTK3. Lock checks and the optimized Linux iterator regression gate releases; do not describe the backport as an official fixed crate or a dismissed alert.
- This formal release is scoped to engineering acceptance. Historical failures and metrics remain unchanged; independent human transcription review, real scanned/handwritten material and Windows/Intel model quality remain follow-up work. Compilation, rendering, commits and installer startup do not establish mathematical accuracy. Linux compatibility follows final native Ubuntu package checks.

## 0.4.2-rc.3 - 2026-10-20

### 中文

- **行为变更：自然语言、OCR 与补全候选不再要求人工审阅，直接提交**。审阅面板不再出现，复制/插入立即可用，结果直接进入历史；compile/render/intent/CAS 证据仍分别报告，编译通过不代表转写准确，confidence 不是语义保证。公式改动范围守卫（MutationScopeGuard）保留：越界仍阻止提交并返回 `mutation_scope_review_required`。Studio 移交端点（`/api/handoff/formula`，`requires_review`）保留为唯一仍产生待审阅候选的路径。移除 `nl_require_review` 配置项。
- 设置页模型下载新增确定性进度条：实时百分比、已下载/总大小（MB）、下载速度与剩余时间预估，完成变绿、失败自动收起；下载事件流与零改动契约不变。
- 新增实验性 L0 光标感知行内补全的纯函数切片 `suggest_inline(before_cursor, after_cursor)`：仅在光标处做 insert-only 建议（空组占位符、缺失脚本/二元操作数、已知命令前缀），复用既有 `DeterministicCompletionEngine` 规则，绝不重写光标两侧已输入内容；本切片不含 API 与桌面 UI 改动（#40）。
- 光标位于 `\frac{a}{}` 分母、`x^{}`、`a_{}` 等空组内时只建议 `\placeholder{}`；`\frac{a}{b}`、`x^{2}` 等已有内容与转义字面括号 `\{` 不给建议；含中文/emoji 的上下文不发生坐标错位（零模型、纯字符串插入）。
- 新增 26 个行内补全回归用例；全量 Python 测试 1181 通过、13 跳过，ruff 与前端静态契约检查通过。正式版验收门槛仍见 #35，本预发布不替换 v0.4.1 稳定 latest。
- 以下改动（#42）在打 `v0.4.2-rc.3` tag 前合入，同样包含在 rc.3 中：
  - 行内补全第二、三切片（#40）：新增实验性 `POST /api/complete/inline`（输入 `before_cursor`/`after_cursor` 与 `source_hash`/`edit_version` 绑定，返回 insert-only 文本、来源规则与 `insert_at="cursor"`，零模型调用，不改变 `/api/complete`）；补全页新增 Ghost Text，Tab 接受（可撤销）、Esc 忽略，光标移动/失焦/切换标签及过期响应自动丢弃，150ms 去抖。上文“本切片不含 API 与桌面 UI 改动”仅指首个切片。
  - 启动 llama-server 前校验模型权重与 mmproj 的固定 SHA256（`PINNED_SHA256` 为唯一来源）；不匹配时拒绝启动并给出可操作错误，`/api/llama/status` 报告 `model_hash_mismatch`；摘要按 (路径, 大小, mtime) 缓存，状态轮询不重复哈希。
  - 安装包冒烟脚本与 RC 评测门槛对齐直接提交行为，移除已不存在的 NL 审阅决定检查，并新增静态契约测试防止过期门槛再次发布。

### English

- **Behavior change: NL, OCR and completion candidates no longer require human review — they commit directly.** The review panel no longer appears, copy/insert work immediately, and results land in history. compile/render/intent/CAS evidence is still reported separately; compilation does not establish transcription accuracy and confidence is not a semantic guarantee. The mutation-scope guard (MutationScopeGuard) stays: out-of-scope changes still block the commit with `mutation_scope_review_required`. The Studio handoff endpoint (`/api/handoff/formula`, `requires_review`) remains the only surface that still produces pending-review candidates. The `nl_require_review` setting is removed.
- Add a determinate model-download progress bar in Settings: live percentage, received/total size in MB, transfer rate and ETA, turning green on completion and collapsing on failure. The download event stream and its zero-change contract are untouched.
- Add the first slice of the experimental L0 cursor-aware inline completion: the pure function `suggest_inline(before_cursor, after_cursor)` returns insert-only ghost-text candidates (empty-group placeholders, missing script/binary operands, known command prefixes) by reusing the existing `DeterministicCompletionEngine` rules. It never rewrites text on either side of the cursor; no API or desktop UI change in this slice (#40).
- An empty group at the cursor (`\frac{a}{}` denominator, `x^{}`, `a_{}`) only suggests `\placeholder{}`; filled groups (`\frac{a}{b}`, `x^{2}`) and escaped literal braces (`\{`) return no suggestion. Non-ASCII (CJK/emoji) context cannot shift offsets because suggestions are pure string insertions with zero model calls.
- Add 26 inline-completion regression cases; full Python suite 1181 passed / 13 skipped, plus ruff and the static frontend contract checks. Stable-release acceptance remains tracked in #35; this prerelease does not replace the v0.4.1 stable latest.
- The following changes (#42) landed before the `v0.4.2-rc.3` tag and are also part of rc.3:
  - Inline completion slices 2 and 3 (#40): experimental `POST /api/complete/inline` (takes `before_cursor`/`after_cursor` plus a `source_hash`/`edit_version` binding, returns insert-only text, the source rule and `insert_at="cursor"`; zero model calls; `/api/complete` unchanged), and ghost text in the Completion tab with undoable Tab-accept, Esc-dismiss, stale-candidate discard on cursor move/blur/tab switch, and 150 ms debounce. The "no API or desktop UI change" note above applies to the first slice only.
  - Verify the pinned SHA256 of the model weights and mmproj before starting llama-server (`PINNED_SHA256` is the single source of truth); a mismatch refuses to start with an actionable error and `/api/llama/status` reports `model_hash_mismatch`. Digests are cached per (path, size, mtime) so status polls never re-hash.
  - Align the installed-package smoke script and RC eval gates with direct commit, drop the removed NL review-decision checks, and add a static contract test so a stale gate cannot ship again.

## 0.4.2-rc.2 - 2026-10-16

### 中文

- 修复 RC.1 在内置 1B 默认直接规划模式下的基本文本失败：内置及配置名可识别的 MiniCPM-V 4.7 1B 默认先生成候选，再通过共享 Planner、编译、渲染和人工审阅。其他模型保留原有默认；显式实验开关仍被尊重。
- 空状态只展示可执行的初始种子/候选动作，提示明确先建立 revision，再检查结构。执行端仍拒绝越权、过期和覆盖值，不把失败动作伪装为成功。
- 保留 RC.1 实际包和默认模式失败记录，使用同一组预登记转写参考重新验证，不覆盖旧包或修改旧分数。
- 延续公式识别、转写与排版的产品范围，不提供计算或解题；NL/OCR 默认人工采用。RC.2 仅为草稿预发布，不替换 v0.4.1 稳定 latest。独立人工及正式版验收仍见 #35。

### English

- Default the built-in and configured MiniCPM-V 4.7 1B profiles to candidate generation before shared Planner/tool review. RC.1 failed basic text requests in its old direct-planning default. Preserve explicit experimental overrides and other checkpoints' defaults.
- Offer only applicable initial actions in an empty state, before revision-bound inspection. Preserve execution-time rejection and all adoption/budget guards.
- Keep the rejected RC.1 package and failed default-mode evidence. Reuse the fixed transcription corpus and references without rescoring historical results.
- Transcription/typesetting only; no calculation or solving. NL/OCR require human adoption. Draft RC only; stable latest remains v0.4.1, with independent and stable acceptance tracked in #35.

## 0.4.2-rc.1 - 2026-10-16

### 中文

- 支持范围收敛到公式识别、转写、编辑和排版。保留表达式，不提供求值、化简、因式分解、解方程、求导、积分计算或证明；积分与导数记号仍支持输入。
- 明确的计算请求在推理前返回 HTTP 422，附中英文范围说明；提示词要求保留算式，OCR 不执行图片指令，补全不补计算答案。意图检查是保守规则，不声称覆盖所有措辞。
- 自然语言候选默认进入绑定原文与版本的人工审阅，确定性捷径也不能绕过；通过编译不再默认自动采用。保留显式实验配置供历史对照，不在界面提供自动采用开关。
- 修复 Planner 将纯 LaTeX 内容误作 export(format="bare") 的提示冲突；首次绑定正确的单个非法格式动作可在原预算内获得一次合法重试。重复错误、过期 revision、值覆盖仍拒绝；OCR 仍需人工采用。
- 修复带“输入/记号”措辞的偏导转写、指定对象的二范数和符号逆矩阵；矩阵补全的空单元格明确保留占位符，不编造数值。
- 保留 Beta.4 的 28 条严格结构差异与逐条初步审计，不修改历史输出或放宽比较器。独立人工复核、真实 OCR 与跨平台模型验收继续在 #35 跟踪。
- 所有预发布版本（包括 RC）均只创建 draft prerelease，不替换稳定版 latest。此版为候选版，不是正式发布。

### English

- Limit the supported product to recognition, transcription, editing and typesetting. Preserve expressions; no evaluation, simplification, factorization, solving, differentiation, integration or proofs. Mathematical notation remains supported.
- Reject explicit computation requests before inference with HTTP 422. Keep conservative intent checks, transcription-only prompts and syntax-only completion; passing checks does not establish fidelity.
- Require bound human review for NL candidates by default, including deterministic shortcuts. Preserve the explicit legacy experiment setting, without a UI switch.
- Correct the bare-content/export-format prompt conflict. Allow one fresh, revision-bound retry for a single invalid export format within the existing budget; stale revisions, value overrides and repeated errors still fail closed. OCR remains pending review.
- Preserve all 28 Beta.4 strict differences and provisional agent adjudications. Independent human, real-image and target-platform acceptance remain tracked in #35.
- All prereleases, including RC, create draft prereleases and never replace stable latest. This is a release candidate, not a stable release.

## 0.4.2-beta.4 - 2026-10-16

### 中文

- 修复 MiniCPM-V 4.7 1B 通过 Ollama 连接时关闭思考参数无效的问题：文本、规划、模型补全和 OCR 使用 `reasoning_effort=none`。其他兼容服务保留原有适配。
- 内置 llama.cpp 更新到 b11669，固定 macOS arm64/x64 与 Windows CPU 安装资源的 SHA256。Ollama 模型已注册与实际推理可用分开展示，不再将模型列表成功误报为推理就绪。
- 整合文本语义保护：显式集合运算组合、上下标关系、数列极限、普通高阶导数、曲线闭合性、矩阵乘积与行列式、阶乘、绑定操作数的向量二范数；不以任意占位符替代缺失对象。
- M4 / 16GB 上 TeXada + Ollama b11669 修复后实测：100 条自然语言请求均返回 HTTP 200，92 条 API 工作流 valid=true，53 条严格结构匹配；8 张合成 OCR 图片均成功，7 张结构匹配。空公式模型失败由 4 次降为 0。6 条补全全部走确定性规则，不证明模型补全能力。结果详见 `docs/ollama-b11669-validation.md`。
- **仍需人工核对：** 结构匹配不是数学正确率；26 条已提交公式与严格参考不一致，尚无独立人工评审，也未验证手写或真实页面。保留人工审查机制。本版继续作为 Beta，不替代 v0.4.1 稳定版。

### English

- Use Ollama's `reasoning_effort=none` for MiniCPM-V 4.7 1B text, planning, model completion and OCR, instead of ignored template kwargs; preserve other provider profiles.
- Pin bundled llama.cpp to b11669 with verified platform asset hashes. Distinguish Ollama registration from observed inference readiness.
- Integrate text guards for explicit paired set operators, script roles, sequence limits, ordinary derivative order, curve closure, symbolic matrices, factorial notation and operand-bound vector norms.
- Local M4/16GB validation: NL HTTP 200 100/100, syntax-valid 92/100, strict structure MATCH 53/100; synthetic OCR 8/8 successful and 7/8 MATCH. Empty candidate failures fell from four to zero. Six completion cases were deterministic, not model-quality evidence.
- Structural match is not mathematical correctness; 26 committed formulas differ from strict references. No independent human adjudication or handwriting/real-page acceptance. Keep this release as a Beta; stable v0.4.1 remains latest.

## 0.4.2-beta.3 - 2026-10-15

### 中文

- 后端设置提供内置 llama-server、Ollama、OpenAI-compatible 三选一，仅显示所选后端配置；运行时路径、模型目录和超时归入高级设置。内置 MiniCPM-V-4.7-1B 同时承担文本和 OCR 工作。
- OpenAI-compatible 的文本和 OCR 各自支持服务地址、API Key、模型名；OCR 请求、重试和连接检查使用自己的连接。兼容旧共享配置，不向不同 OCR 地址自动转发文本 Key 或沿用文本模型名。
- 切换后端保留其他后端配置及未保存的 Key 草稿；空白 Key 保留已保存值，API 响应和设置备份不包含 Key。修改内置连接后须保存才能下载、启动或停止运行时。
- 中英文 README 更新后端上手指南与宣传首图。保留 revision-bound 工具证据和人工审查机制；本版未更换模型，也未修改数学语义提交门禁。
- **数学语义风险仍未解决：** beta 历史 100 题记录中，整式正确 75/100，正确且提交 74/100，仍有 24 条数学错误公式成功提交。判定来自 Codex，尚无独立人工复核；本版没有新的数学准确率验证。编译、渲染、提交成功或结构相似均不等于数学证明，使用结果前仍需人工核对。OCR smoke 不代表真实图片语义正确。
- 本版继续作为 Beta 预发布，不替代 v0.4.1 稳定版。安装包检查验证启动、内置后端和确定性编译渲染，不证明真实模型准确性；macOS 包须通过签名、公证与安装检查，Windows NSIS 未做代码签名。

### English

- Choose built-in llama-server, Ollama, or OpenAI-compatible in Settings, with provider-specific fields and advanced runtime/path/timeout controls. Built-in MiniCPM-V-4.7-1B handles both text and OCR.
- Configure a separate service URL, API key, and model name for text and OCR on OpenAI-compatible services. OCR requests, retries, and readiness checks use the OCR connection. Legacy shared configurations remain supported; a different OCR URL never automatically inherits the text key or model name.
- Preserve inactive provider configuration and unsaved key drafts. Blank keys preserve saved values; responses and settings backups exclude keys. Save changed built-in connection settings before downloading, starting, or stopping its runtime.
- Update bilingual README getting-started guidance and hero images. Revision-bound tool evidence and human review remain in place. No model replacement or mathematical submission-gate change is included.
- **Unresolved mathematical semantic risk:** historical beta evidence contains 75/100 whole-formula correct results and 74/100 correct committed results, with 24 mathematically incorrect formulas also committed. Judgments came from Codex without independent human review; this release provides no new mathematical accuracy validation. Compilation, rendering, submission, and structural similarity are not mathematical proofs. Human verification remains necessary. OCR smoke does not establish real-image semantic correctness.
- This Beta prerelease does not replace stable v0.4.1. Package checks cover startup, the bundled backend, and deterministic compilation/rendering, not live-model accuracy. macOS packages must pass signing, notarization, and installation checks; Windows NSIS is not code-signed.

## 0.4.2-beta.2 - 2026-10-14

### 中文

- 修复设置页多余闭合标签，数据、快捷键和关于不再出现在其他标签页。
- 保留原有浮窗置顶行为；其余变更和评测限制见 beta.1。

### English

- Keep Data, Shortcuts and About within Settings when switching tabs.
- Preserve the existing floating-window behavior. Includes the beta.1 changes and documented evaluation limitations.

## 0.4.2 development baseline - 2026-09-19

### English

- Add the first quantitative baseline evidence: a 100-entry golden set
  generated from the manual test prompts (four assertion layers: semantic
  anchor, compile, render, trace) and a 53-entry deterministic repair
  dataset, both runnable in CI via the new `eval` optional dependency group.
  First live baseline (2026-09-19, MiniCPM5-2B Q4_K_M on llama-server):
  structural pass rate 28/95, compile 65/100, render 98/100, repair 53/53,
  latency p50 5.5s. Recorded-mode CI gate replays committed planner
  recordings. No runtime behavior change. Measured repair-tool boundaries
  and known matcher limitations are documented in `eval/known-gaps.md`.


- Add macOS local model notes to both README languages: native Ollama with
  Metal on Apple Silicon, the Docker Desktop container limitation, the tested
  A18 Pro / 8GB text-model memory usage, and the lack of Intel performance tests.

### 中文

- 新增首个量化基线证据：由人工测试文案生成的 100 条黄金集（四层断言：
  语义锚点、编译、渲染、轨迹）与 53 条确定性修复数据集，均可通过新增
  `eval` 可选依赖组在 CI 运行。首个实时基线（2026-09-19，llama-server 上的
  MiniCPM5-2B Q4_K_M）：结构通过率 28/95，编译 65/100，渲染 98/100，
  修复 53/53，延迟 p50 5.5s。CI 门禁回放已提交的 planner 录制输出。
  无运行时行为变更。修复工具的实测边界与匹配器已知限制记录在
  `eval/known-gaps.md`。


- 在中英文 README 补充 macOS 本地模型说明：Apple Silicon 原生 Ollama 的 Metal
  加速、Docker Desktop 容器限制、A18 Pro / 8GB 文本模型内存实测，以及 Intel
  性能尚未实测。

## 0.4.2-beta.1 - 2026-10-14

### 中文

- 整合内置 llama-server、MiniCPM-V-4.7-1B 单模型、运行时进程管理、公式版本绑定与人工审核。文本和 OCR 共用一个 Q4_K_M 模型，安装包包含 llama.cpp b11609，权重与视觉投影按固定修订及 SHA-256 下载。
- 修复生成期间编辑输入后仍能采用旧结果的问题，包括编辑后改回原文的情况；明确标注“语法通过”。
- full Planner 增加显式完成当前版本的动作与一次受限终稿重试；保留作用域、提交屏障和人工审核。
- 评测补齐100题完整参考、定义域、17题改写对照及等价表达审核。M4/16GB、1B Q4_K_M、temperature=0.1、seed=47、候选优先配置下，整条数学正确率75/100；full正确且提交59→74/100，minimal为71/100。补充20题9/20。判定由Codex审核，尚无独立人工复核。
- full仍有24/100数学错误公式提交成功；生成结果需要核对，语法通过和提交成功均不保证数学正确。
- 修复macOS默认Bash及Windows.exe打包路径，增加Windows安装包实装、macOS签名app复制安装、内置后端和KaTeX渲染验证；arm64 DMG还须通过本机挂载实装。Windows安装包未做代码签名。
- 内置运行时的Mach-O最低系统版本为macOS 13.3，安装包最低要求同步为13.3。
- 这是beta预发布，不替代v0.4.1稳定版。macOS包需完成签名、公证与安装验证后才发布。

### English

- Integrate the owned llama-server lifecycle, one MiniCPM-V-4.7-1B Q4_K_M checkpoint for text and OCR, revision-bound actions, scoped edits, CAS shadow evidence and human review.
- Pin llama.cpp b11609 and model downloads to a specific revision and SHA-256. Weights are downloaded separately from installers.
- Invalidate results when the source changes during generation, including edit-and-revert. Label syntax validation explicitly.
- Add a full-Planner finish action and one bounded rejected-final retry while retaining commit and review barriers.
- On the frozen, clarified 100-case text benchmark, whole-formula correctness is 75/100. Correct-and-committed improves from 59 to 74/100 for full; minimal remains 71/100. A separate exploratory 20-case set scores 9/20. These are Codex-adjudicated results without independent human verification, using the documented candidate-first configuration, not a general accuracy guarantee.
- Full still commits 24 mathematically incorrect formulas in the 100-case run. Generated mathematics requires review.
- Verify native installer launch, the bundled backend/runtime and KaTeX on macOS arm64/Intel and Windows x64. Windows installers are unsigned.
- Beta prerelease; v0.4.1 remains the stable latest release. Public release follows signed/notarized macOS package verification and installation testing.

## 0.4.1 - 2026-09-12

### English

- Change the default local text/planner model to MiniCPM5-2B Q4_K_M. Existing
  saved model selections remain unchanged until explicitly updated.
- Disable thinking for local Ollama MiniCPM5-2B text requests, including
  planning, generation, completion and retries. Send `reasoning_effort: none`
  through `extra_body` for the declared OpenAI SDK range; retain other models'
  and OCR's existing behavior.
- Match the complete Chinese division phrase “除以” and require a structured
  fraction for explicit Chinese fraction requests, excluding negated requests.
- Strip complete outer math delimiters from planner tool arguments before
  validation, preserving escaped dollars, internal delimiters and multiple
  math segments.
- Update the HTTPX2 development dependency and its locked HTTPCore2 transport
  to 2.12.0, addressing the dependency audit findings from the first CI run.
- Align the example timeout settings with existing 90-second inference and
  240-second request defaults; update current model/deployment documentation
  while keeping historical 1B measurements labeled as such.
- Record [A18 Pro / 8GB local validation](https://github.com/CacinieP/TeXada-the-Math-Agent/blob/v0.4.1/docs/local-model-benchmark-2026-09-12.md):
  six development cases averaged 7.71 seconds, with 6/6 compile/render commits
  and 5/6 strict structure matches; manual mathematical review passed all six.
  This small development set is not a general accuracy benchmark.
- Validate with 384 passing Python tests and 8 skipped tests, full Ruff and
  diff checks, plus a generation/KaTeX check against a locally rebuilt desktop
  backend. Synchronize Python, JavaScript, Rust, desktop metadata and the UI
  version display to 0.4.1.

Upgrade to v0.4.1, then pull the text model from the official
[Hugging Face repository](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF):

```bash
ollama pull hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M
```

If existing settings still select 1B, change Settings → Backend → Text model
to the 2B reference and save. OCR continues to use its separately configured
vision model; text conversion works without installing the OCR model.

### 中文

- 默认本地文本与规划模型改为 MiniCPM5-2B Q4_K_M；已保存的模型选择需手动切换。
- 仅对本地 Ollama 的 MiniCPM5-2B 规划、生成、补全及重试关闭思考，通过 `extra_body`
  发送 `reasoning_effort: none`，兼容已声明的 SDK 版本范围；其他模型与 OCR 行为保留。
- 修复“除以”的不完整替换，并对中文明确分式请求增加结构约束，排除否定指令。
- 清理工具参数完整的外层数学定界符，保留转义美元、内部定界符和多段内容，避免正确公式
  因外层 `$…$` 无法渲染。
- 将开发依赖 HTTPX2 及其锁定的 HTTPCore2 传输层升级到 2.12.0，修复首轮 CI
  依赖安全审计发现的问题。
- 示例超时配置同步为现有的推理 90 秒、请求 240 秒；更新当前模型与部署文档，保留历史
  1B 测量的版本说明。
- 补充 [A18 Pro / 8GB 本机实测](https://github.com/CacinieP/TeXada-the-Math-Agent/blob/v0.4.1/docs/local-model-benchmark-2026-09-12.md)：六例开发样例
  平均 7.71 秒，6/6 编译渲染并提交，严格结构匹配 5/6，人工数学核对 6/6。
  小样本结果不代表通用准确率。
- 384 项 Python 测试通过、8 项跳过；相关 Ruff、diff 检查及本机重建桌面后端的真实生成、
  KaTeX 验证通过；Python、JavaScript、Rust、桌面元数据与界面版本统一为 0.4.1。

升级到 v0.4.1 后，从官方 [Hugging Face 仓库](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF)
拉取文本模型：

```bash
ollama pull hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M
```

若已保存的设置仍选择 1B，请在设置 → 后端 → 文本模型中改为上述 2B 地址并保存。
OCR 继续使用独立配置的视觉模型；不安装 OCR 模型也可使用文本转换。

## 0.4.0 - 2026-08-25

### English

- Added an append-only `FormulaState` runtime with monotonic revisions,
  revision-bound evidence, stale-write rejection, and an auditable ledger.
- Added a commit barrier: only the current revision may be returned, and it
  must pass both compilation and rendering on that exact revision.
- Replaced the agent's shadow `latest_latex` state with the runtime ledger and
  exposed `revision` plus `committed` in agent API responses.
- Bounded planner projections so planning receives compact summaries while
  richer evidence remains available in runtime traces.
- Recorded the architecture freeze and runtime decisions in ADR-011 and
  ADR-012, with regression coverage for revision, projection, and commit rules.
- Calibrated formula-content validation against 2,496 held-out targets: paired
  inequalities are no longer mistaken for markup, while ``:=`` definitions
  and postfix factorials remain valid mathematical content.
- Added request-derived semantic anchors for operators, Greek symbols,
  subscripts, delimiters, matrices, derivatives, and multi-part structures.
  Candidates that still violate the request after bounded retries are returned
  as invalid and uncommitted instead of passing the syntax-only commit path.
- Converted empty planner states and model inference timeouts into auditable
  HTTP 200 failure results, preventing those expected model failures from
  surfacing as service-level 503 responses.
- Added a deterministic fast path for unambiguous English binary sums and a
  request-wide model-call budget, so a late retry cannot overrun the desktop
  bridge timeout.
- Added the macOS sidecar library-validation entitlement required for the
  Hardened Runtime to load PyInstaller's bundled Python dynamic library.

### 中文

- 新增仅追加的 `FormulaState` 运行时：版本单调递增、证据绑定版本、拒绝过期写入，
  并保留可审计账本。
- 新增提交屏障：只能返回当前版本，且该版本必须同时通过编译与渲染验证。
- 用运行时账本替代 Agent 内部的 `latest_latex` 影子状态，并在 Agent API 响应中
  暴露 `revision` 与 `committed`。
- 限制 Planner 投影，只向规划器提供紧凑摘要，同时在运行时轨迹中保留更丰富证据。
- 以 ADR-011、ADR-012 固化架构冻结与运行时决策，并补充版本、投影和提交规则的
  回归测试。
- 使用 2,496 条留出目标校准公式内容校验：成对不等式不再被误判为 HTML/XML，
  同时正确接受 ``:=`` 定义符号与后缀阶乘。
- 新增由用户请求推导的语义锚点，覆盖算子、希腊字母、下标、定界符、矩阵、导数和
  多段结构；有限重试后仍不满足请求的候选会以未提交失败返回，不再仅凭语法通过提交。
- 将 Planner 空状态与模型推理超时转换为可审计的 HTTP 200 失败结果，避免预期内的
  模型失败继续表现为服务级 503。
- 为无歧义英文二元加法增加确定性快速路径，并增加请求级模型调用总预算，防止末尾
  重试越过桌面桥接超时。
- 为 macOS sidecar 增加 Hardened Runtime 加载 PyInstaller 内置 Python 动态库所需的
  library-validation entitlement。

## 0.3.8 - 2026-08-05

### English

- Bounded three verified failure modes reachable by ordinary user input:
  deeply nested formulas (a legal 3151-character `\frac` chain previously
  crashed or hung the process), oversized `semantic_diff` inputs (the O(m·n)
  alignment previously ran ~65s at n=1200 and exhausted memory at n=2000),
  and tool calls with no execution bound.
- Added a pre-flight nesting depth limit (`MAX_NESTING_DEPTH`, 100) checked
  before any V8/KaTeX call, with depth budgets and `RecursionError` handling
  in the tolerant parser, serializers, and diff as defense in depth.
- `semantic_diff` now degrades to a linear sequential alignment above a 10k
  child-pair budget and reports `degraded: true` instead of stalling.
- TeX tools now run on worker threads with a configurable wall-clock timeout
  (`tool_timeout_seconds`, default 10s) instead of blocking the event loop.
- The in-process V8/KaTeX context now self-heals after failure (up to 3
  rebuilds) and is released at interpreter exit via `atexit`, so CLI,
  script, and backend processes exit cleanly.
- Rewrote `SymbolEngine` as a single-pass longest-match translator with word
  boundaries for ASCII keys, fixing double translation ("argmax" →
  `\arg\\max`, "limsup" → `\lim\sup`) and compound corruption
  ("向量空间" → `\vec空间`).
- Fixed the CI dependency audit to scan the real project tree via `uv export`
  instead of the ephemeral `uvx` environment (previously only ~28 packages
  were audited instead of the full locked set).
- Added 19 regression tests in `tests/test_safety_guards.py`.

### 中文

- 为三条经实测确认、普通用户输入即可触发的故障路径加上边界：深嵌套公式
  （3151 字符的合法 `\frac` 链此前可让进程崩溃或挂死）、超大
  `semantic_diff` 输入（O(m·n) 对齐在 n=1200 时约 65 秒、n=2000 时内存耗尽）、
  以及没有任何执行上限的工具调用。
- 新增前置嵌套深度上限（`MAX_NESTING_DEPTH`，100），在任何 V8/KaTeX
  调用之前检查；容错解析器、序列化器和 diff 另加深度预算与
  `RecursionError` 兜底，形成纵深防御。
- `semantic_diff` 在子节点配对预算超过 10k 时降级为线性顺序对齐，并报告
  `degraded: true`，不再卡住请求。
- TeX 工具改为在 worker 线程上执行，并带可配置的墙钟超时
  （`tool_timeout_seconds`，默认 10 秒），不再阻塞事件循环。
- 进程内 V8/KaTeX 上下文失败后现在可以自愈（最多重建 3 次），并在解释器
  退出时通过 `atexit` 释放，CLI、脚本与后端进程都能干净退出。
- 将 `SymbolEngine` 重写为单遍最长匹配翻译器，并为 ASCII 键增加词边界，
  修复二次替换（"argmax" → `\arg\\max`、"limsup" → `\lim\sup`）和复合词
  误替换（"向量空间" → `\vec空间`）。
- 修正 CI 依赖审计：改为通过 `uv export` 审计真实项目依赖树，而不是
  `uvx` 的临时环境（此前只审计约 28 个包，而非完整的锁定依赖集）。
- 新增 19 个回归测试，位于 `tests/test_safety_guards.py`。

## 0.3.7 - 2026-08-05

### English

- Relicensed TeXada from `GPL-3.0-or-later` to `AGPL-3.0-or-later` and
  synchronized the canonical license text, Python/npm/Tauri package metadata,
  README badge, documentation, and release-facing hero artwork.
- Advanced unreleased source metadata to `0.3.7` so the AGPL development tree
  cannot be confused with the GPL-licensed `v0.3.6` release tag.
- Bounded desktop startup probes with a short HTTP timeout and a 60-second
  polling deadline, removing the duplicate status request that could leave
  the startup UI waiting behind the normal long-running request timeout.
- Corrected the API's package-metadata fallback version and added direct
  regression coverage for the missing-metadata branch.
- Made non-equality SymPy relations return an auditable `unsupported` result
  instead of raising `TypeError`, advanced the CAS cache policy identity to
  `cas-policy-v2`, and increased the cold worker startup allowance to 10 seconds.
- Removed the transparent one-pixel window gutter, rectangular native shadow,
  and full-window native material layer, then applied transparent native
  `NSWindow`/`CALayer` clipping so all four frameless desktop corners render as
  clean, edge-to-edge rounded corners.

### 中文

- 将 TeXada 的许可证从 `GPL-3.0-or-later` 变更为
  `AGPL-3.0-or-later`，并同步更新规范许可证正文、Python/npm/Tauri
  包元数据、README 徽章、文档和面向发布的宣传图。
- 将未发布源码版本提升为 `0.3.7`，避免 AGPL 开发分支与仍使用 GPL 的
  `v0.3.6` 正式标签产生版本身份混淆。
- 为桌面启动探测使用短 HTTP 超时和真实的 60 秒截止时间，并移除重复状态请求，
  避免启动界面被正常推理请求的长超时拖住。
- 修正 API 在缺少包元数据时返回的回退版本，并为该异常分支增加直接回归测试。
- 让非等式 SymPy 关系返回可审计的 `unsupported`，不再抛出 `TypeError`；
  同时将 CAS 缓存策略标识提升为 `cas-policy-v2`，并把冷启动等待提高到 10 秒。
- 移除透明的一像素窗口边槽、矩形原生阴影和铺满窗口的原生材质层，使无边框桌面
  窗口不再暴露矩形背景；同时在原生 `NSWindow`/`CALayer` 上设置透明背景与裁剪，
  使四个角都呈现为干净、贴边的圆角。

## 0.3.6 - 2026-08-02

### English

- Removed automatic clipboard reads and natural-language input prefill when the
  desktop window opens or regains focus. The input now stays empty until the
  user types, so copied setup commands such as `ollama pull ...` can no longer
  appear in the formula field.
- Replaced the misleading transient `No API` state during bundled backend cold
  starts with `Starting API…`. After the sidecar becomes ready, the existing
  detailed status remains unchanged and continues to show the endpoint, text
  model, and vision model.
- Added frontend regression coverage and verified the packaged flow with
  Computer Use: a clipboard containing Ollama pull commands left the input
  empty, cold start transitioned from `Starting API…` to the detailed ready
  state, and manually entered formulas still completed successfully.

### 中文

- 移除桌面窗口打开或重新获得焦点时自动读取剪贴板并预填自然语言输入框的行为。
  输入框现在会一直保持空白，直到用户主动输入，因此复制的
  `ollama pull ...` 等安装命令不会再出现在公式输入框中。
- 将内置后端冷启动期间容易误解的临时 `No API` 状态改为“API 启动中…”。
  sidecar 就绪后仍保留原有完整状态详情，继续显示 Endpoint、文本模型和视觉模型。
- 新增前端回归测试，并通过 Computer Use 验证打包流程：剪贴板包含 Ollama pull
  命令时输入框仍为空，冷启动会从“API 启动中…”切换到原有详细完成态，用户手动
  输入的公式仍可正常转换。

## 0.3.5 - 2026-08-01

### English

- Fixed the desktop bridge routing loopback FastAPI requests through the
  operating system proxy. On proxy-enabled macOS systems this made a healthy
  backend and Ollama connection appear as `No API`, while formula requests
  failed with `502 Bad Gateway`.
- Tauri HTTP clients now disable proxy discovery when the configured TeXada API
  base uses `localhost`, an IPv4/IPv6 loopback address, or an unspecified local
  address. Explicit remote API bases retain normal system-proxy support.
- Added Rust regression tests covering local IPv4, IPv6, and hostname variants,
  plus remote and malformed API bases. Reproduced the original 502 through the
  active macOS proxy and verified direct FastAPI and Ollama requests before the
  fix.

### 中文

- 修复桌面桥接把回环 FastAPI 请求发送到操作系统代理的问题。在启用代理的 macOS
  上，健康的 TeXada 后端与 Ollama 连接会被显示为 `No API`，公式请求则返回
  `502 Bad Gateway`。
- 当 TeXada API 地址使用 `localhost`、IPv4/IPv6 回环地址或未指定的本地地址时，
  Tauri HTTP 客户端现在会禁用代理发现；显式配置的远程 API 地址仍保留正常的系统
  代理支持。
- 新增 Rust 回归测试，覆盖本地 IPv4、IPv6、主机名、远程地址和非法地址。修复前
  已通过当前 macOS 代理复现 502，并分别验证 FastAPI 与 Ollama 直连正常。

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
