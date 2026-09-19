# TeXada 迭代路线图 — v0.4.1 → v1.0

Status: Active（当前唯一权威排期）

制定日期：2026-09-19

基线：`main` @ v0.4.1（2026-09-12 发布）

本路线图回答两个问题：**接下来要做哪些架构决策**，以及**以什么顺序、什么门槛做**。
它是排期与门槛的唯一权威文档。与现有文档的关系：

| 文档 | 角色 |
|---|---|
| [architecture-freeze-v0.4.md](architecture-freeze-v0.4.md) | 永久分层、里程碑范围、变更门禁（词汇与不变量） |
| 本路线图 | 决策清单、迭代顺序、验收门槛（排期） |
| [adr/](adr/) 目录 | 单个架构决策的完整论证（问题 / 决策 / 备选 / 取舍） |
| 8 月外部评审迭代建议（本地文档） | 评审证据与历史建议；排期部分以本路线图为准 |

本路线图不改变 freeze 文档冻结的词汇与不变量。里程碑表中的范围漂移记录在
§2，不作为新冻结。

## 1. 决策清单（D1–D7）

| 编号 | 决策 | 结论 | ADR |
|---|---|---|---|
| D1 | 证据工程定位 | 横向质量轨道，贯穿所有里程碑，不占 v0.x 编号 | [013](adr/013-golden-set-evidence.md) |
| D2 | v0.4.1 工具契约归属 | 并入 v0.5 设计阶段，作为 patch 接口前置设计；v0.4.1 标注 superseded | [014](adr/014-tool-runtime-contract.md) |
| D3 | v0.5 语义补丁模型 | planner 产 patch + 确定性应用器 + Scope Guard + 失败回退；patch 要么产生新 revision 要么被显式拒绝 | [015](adr/015-semantic-patch-apply-model.md) |
| D4 | arXiv import 处置 | 不复活，记为放弃实验 | 本文档 §2 |
| D5 | CAS 收敛 | 保留 `cas-eval` 门禁为回归资产，产品路线图上标注为文档化未来方向 | 本文档 §5 |
| D6 | 模型依赖测试的 CI 边界 | 真实模型跑法手动/tag 触发；常规 CI 只跑确定性断言与录制 fixture | [013](adr/013-golden-set-evidence.md) |
| D7 | 本地模型运行时 | 双运行时：内置 llama-server sidecar 为默认，Ollama 与 OpenAI-compatible 为兼容后端 | [016](adr/016-local-model-runtime-llama-server.md) |

## 2. 已知漂移与事实修正

以下事实在排期前必须显式记录，避免后续读者按旧文档预期理解当前状态。

1. **v0.4.1 里程碑漂移。** freeze 文档 v0.4.1 行承诺 Capability Probe /
   schema validation / affordance policy / execution contract，但 `src/texada`
   中不存在任何 capability 相关实现（`src/texada/cas/` 除外，属实验 CAS
   模块）。v0.4.1 实际交付为模型切换（MiniCPM5-2B）与修复。处理：v0.4.1 在
   本路线图中标注为 **"tool contract superseded: merged into v0.5 design"**，
   见 ADR-014。
2. **arXiv import 已废弃。** 2026-08-17 评审时存在的 `feat/arxiv-import`
   分支（第 4 个输入入口）已从远端消失、从未合并。处理：记为放弃实验，
   **不复活**，不为它追加模型能力预算。
3. **全仓库无量化可用性证据。** 无任何准确率 / 召回率 / 通过率数字。这是
   Iteration 1 要解决的核心问题。
4. **8 月评审迭代计划与 freeze 文档口径不一。** 本路线图合并两者：证据工程
   （评审 P0）与里程碑路线（freeze）统一排序。评审文档保留为证据，不再作为
   排期依据。

## 3. 迭代序列

纪律沿用 freeze：**每个迭代只解一个问题**，验收门槛优先于功能清单。
证据轨道（Iteration 1）横向服务于后续所有迭代，不占里程碑编号。

### Iteration 1 — 证据闭环 I：黄金集自动化（发布 v0.4.2）

- **唯一要解的问题**：产品可用性从“不可测量”变为“可测量”。
- **内容**：100 条人工文案参数化黄金集；50 条坏 LaTeX 修复率数据集；
  NL 结构通过率与 repair 修复率两类基线数字；`--extra eval` 可选依赖组。
- **验收门槛**：
  1. 常规 CI 用录制 fixture 与确定性修复集全绿（D6）；
  2. 基线数字写入 README 与 comparison.md，带“非 general benchmark”
     诚实声明（沿用 v0.4.1 开发集口径先例）；
  3. 零 `src/texada` 运行时行为变更（只允许修 bug，须在 CHANGELOG 注明）。
- **不做**：OCR 召回率（缺标注素材，推迟到 v0.6）；前端改动；
  新工具。
- 设计文档：[docs/specs/2026-09-19-golden-set-evidence-i-design.md](specs/2026-09-19-golden-set-evidence-i-design.md)

### Iteration 1.5 — 本地运行时平台：内置 llama-server（发布 v0.4.3）

- **唯一要解的问题**：本地推理从“外部依赖 Ollama”变为“应用内一键启停、
  首次拉取后按需加载”。
- **内容**：llama-server router sidecar（单进程托管文本 + 视觉双模型，
  按需加载 / 空闲卸载）；应用内启停按钮与扩展状态机；首拉 UI
  （GGUF + mmproj 下载到 `~/.texada/models/`，进度 / 取消 / HF 镜像）；
  三选一后端（内置 llama-server 默认 / Ollama 兼容 / OpenAI-compatible）。
- **验收门槛**：
  1. Iteration 1 黄金集在 llama-server 后端上的真实模式通过率不低于
     Ollama 基线（行为中性迁移的唯一证据）；
  2. 8GB 机器双模型按需加载内存实测记录（沿用 A18 Pro 实测先例）；
  3. macOS 公证与 Windows 打包流水线纳入 llama-server 二进制。
- **不做**：移除 Ollama 兼容分支；模型微调或量化自研；云后端扩展。
- 设计文档：待 Iteration 1 完成后按本路线图顺序编写（ADR-016 已给出决策
  与验证清单）。

### Iteration 2 — v0.5 设计：工具契约 + patch 模型（不发版）

- **唯一要解的问题**：语义编辑的接口先于实现存在。
- **内容**：ADR-014 工具执行契约（capability probe / schema 校验 /
  affordance policy）；ADR-015 patch 生产 / 应用 / 回退模型；
  Scope Guard 权限模型；以 Iteration 1 黄金集作为“改动不变量”基线。
- **验收门槛**：ADR-014/015 已 accepted（本次已接受，决策即冻结）；工具执行契约有先行失败的 schema 测试（TDD 红→绿）；Scope Guard 权限矩阵逐条可测。

### Iteration 3 — v0.5 语义补丁 MVP（发布 v0.5）

- **唯一要解的问题**：编辑目标从“字符串”变为“数学对象”。
- **内容**：SourceSpan + Semantic Anchor + patch apply + Scope Guard +
  回退路径；黄金集语义等价回归作为门禁。
- **验收门槛**：
  1. 黄金集通过率不低于 Iteration 1 基线（零回归）；
  2. patch 拒绝 / 回退路径有测试，不存在静默返回原公式的路径；
  3. commit barrier 对 patch 产生的 revision 生效（复用 ADR-011 不变量）。

### 候选迭代（未排期，待拍板）

**Iteration 2.5（候选）— 错误分类与崩溃可见的运行日志。**
来源：`origin/dev/run-guards` 分支（2026-08-21，1 个提交，未合并）。实测
核查结论：其 token budget 想法在 main 已有等价实现
（`reject_model_budget` / `runtime_budget_exceeded`），但两项独有能力
不在 main 中：

1. `error_class`：`ToolObservation` 区分 `'model'`（planner 用错工具/
   参数非法，可自纠）与 `'tool'`（超时、结构限制、内部错误）两类失败，
   连续错误熔断的 halt reason 相应区分为 `model_error_limit` /
   `tool_error_limit`；
2. crash-visible run logs：`backend_unavailable` 与 `cancelled`（499）
   状态行，让请求级日志不再遗漏崩溃路径。

与本迭代的直接关联：Iteration 1 live 基线实测 G-007——MiniCPM5-2B 对
2/100 条输入产生截断的 JSON 工具参数，运行时硬失败且无分类。
`error_class='model'` 正是该场景的原生解法，且崩溃可见日志让此类
失败可在 run log 中量化（当前它在 live 报告中只表现为 2 条
InternalServerError）。建议执行方式：从 `origin/dev/run-guards`
cherry-pick 该提交后在 v0.5 设计阶段适配 ADR-011/012 的 runtime 契约，
不整体合并分支。

### 后续方向（只列方向，不排期）

| 版本 | freeze 定义的问题 | 本路线图备注 |
|---|---|---|
| v0.6 | OCR 保留感知证据 | 含推迟到那时的 OCR 召回率基线（需人工标注素材） |
| v0.7 | 纠错可复用为数据 | Run Trace / Correction / Promotion / Benchmark |
| v1.0 | 产品依赖能力契约而非模型名 | Planner / OCR / Editing 能力契约与稳定 benchmark |

## 4. 迭代纪律

1. 每个迭代的 issue / PR 必须按 freeze 的门禁声明所属永久层与所完成的
   里程碑（或“证据轨道”）。
2. 证据轨道的产出（黄金集、基线数字、修复集）对所有后续迭代是**只增不改**
   的回归资产；修改断言口径需要新 ADR。
3. 模型依赖的验证一律手动 / tag 触发（D6）。常规 CI 保持确定性。
4. 任何“顺手做的架构改动”不进当前迭代——写入路线图决策清单，排队。

## 5. 附带处置

- **CAS**（D5）：`cas-eval` 门禁保留为回归资产，产品路线图上标注为
  文档化未来方向，不排期。与 8 月评审 P3-9 一致。
- **arXiv import**（D4）：记为放弃实验，见 §2。
- **v0.2.5 tag 缺失**（8 月评审 P2-6）：CHANGELOG 有条目但无 tag。
  处理：Iteration 1.5 发布 v0.4.3 时顺手补 tag，不单独排迭代。
