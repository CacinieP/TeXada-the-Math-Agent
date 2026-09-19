# 设计文档：证据闭环 I — 黄金集自动化（Iteration 1 / v0.4.2）

Status: Proposed（待评审）

日期：2026-09-19

所属层：Evidence Layer（横向质量轨道）

对应 ADR：[013-golden-set-evidence](adr/013-golden-set-evidence.md)

对应路线图：[iteration-roadmap-v0.4.1-to-v1.0](../iteration-roadmap-v0.4.1-to-v1.0.md) §3 Iteration 1

## 1. 背景与目标

项目当前无任何量化可用性证据。本迭代把既有的 `docs/test-prompts-100.md`
（100 条人工文案 + 语义锚点 + 5 项人工检查清单）自动化为一套黄金集，并
产出两类基线数字（NL 结构通过率、repair 修复率）。这些数字是后续 v0.5
语义补丁与运行时迁移（ADR-016）的唯一回归门禁。

**唯一要解的问题**：产品可用性从“不可测量”变为“可测量”。

## 2. 范围

做：

- 100 条文案的参数化黄金集（四层断言，两种跑法）
- 50 条坏 LaTeX 修复率数据集（纯确定性，进常规 CI）
- `--extra eval` 可选依赖组与两种跑法的入口
- 基线报告 `eval/reports/<date>-baseline.md`，数字回写 README 与
  comparison.md（带非 benchmark 声明）

不做：

- OCR 召回率（缺标注素材，推迟 v0.6）
- 任何 `src/texada` 运行时行为变更（修 bug 须在 CHANGELOG 注明）
- 新工具、前端改动、comparison.md 的措辞升级（等数字出来后的独立改动）

## 3. 架构

```text
docs/test-prompts-100.md
        │  一次性生成器（脚本 + 测试）
        ▼
eval/golden_set.yaml（结构化 fixture，入库）
        │
        ├── 录制模式（默认，常规 CI）──► FakePlanner（预录 turns）
        │                                │
        │                                ▼
        │                         TeXadaAgentRuntime
        │                                │
        │                    ┌───────────┼───────────┐
        │                    ▼           ▼           ▼
        │              锚点断言    compile/render   run_log 落库
        │
        └── 真实模式（--extra eval，手动/tag）──► 真实本地模型
                                             │
                                             ▼
                                    基线通过率 + 延迟统计

eval/repair_dataset.yaml ──► repair_tex ──► compile + render 双通过（CI）
```

两个关键设计决定：

1. **断言引擎复用 Semantic Layer，不发明第二套解析器。** 锚点与输出都
   过 KaTeX AST → SemanticUnit 归一化，展平为 kind 序列，断言锚点序列是
   输出序列的子序列。这天然消化“空格、`\left`/`\right`、`\dfrac`/`\frac`
   等价写法可接受”的要求。MVP 的子序列匹配可能放过位置不当的锚点，失败
   用例逐条人工判定登记到 `eval/known-gaps.md`，升级为结构包含匹配列入
   Future。
2. **录制模式与真实模式是两个门禁，不合并。** 录制模式验证管线不变量
   （护栏正确）；真实模式验证产品可用性（通过率数字）。常规 CI 只跑
   录制模式与修复集，模型调用永不进门（ADR-013 / D6）。

## 4. 数据与断言

### 4.1 fixture 生成器

`eval/generate_golden_set.py`：解析 markdown 表格，产出
`eval/golden_set.yaml`（字段：`id`、`category`、`input`、`anchor`、
`notes`）。一次性脚本，产出入库，**后续 CI 不依赖 markdown 解析**。

生成器自身有测试（`tests/test_golden_set_gen.py`）：100 条全解析、ID
唯一、锚点非空、8 个分类齐全。

### 4.2 四层断言

对每条文案，运行一次完整 Agent 流程（含 run_log store，tmp_path SQLite）：

| 层 | 断言 | 失败含义 |
|---|---|---|
| 结构锚点 | 锚点 kind 序列是输出 kind 序列的子序列 | 模型丢算符或降级 |
| compile | 钉死 KaTeX 0.17.0 编译通过 | 输出不可编译 |
| render | `render_math` 成功 | 不可渲染 |
| 可观测 | 轨迹可展开且 run_id 在 run_logs 落库 | 可观测性断裂 |

录制模式下，输出来自预录 planner turns；断言验证的是“给定该模型输出，
管线是否产出合法、可提交、可追溯的结果”。

### 4.3 预录 turns 的获取

`eval/record_planner_turns.py`：真实本地模型跑 100 条文案，把每条
（文案 → planner turns → 最终 latex → run_id）写入
`eval/recordings/<run-id>.json`，作为录制模式的 fixture 来源。首次由开
发者本机执行一次并入库；ADR-013 Future 项会把真实 trace 里的小模型坏输
出持续追加为对抗 fixture。

### 4.4 修复率数据集

`eval/repair_dataset.yaml`：50 条典型坏 LaTeX（缺 `\frac` 括号、丢
`\sum` 上下限、`\iiint`→`\int` 降级等）。纯确定性：`repair_tex` 修复后
compile + render 双通过。**不需要模型，直接进常规 CI。**

## 5. 两种跑法

- `uv run --extra dev --extra eval pytest tests/test_golden_set.py`：
  录制模式，进常规 CI。确定性、无模型、可回归。
- `uv run --extra dev --extra eval python eval/run_real_baseline.py`：
  真实模式，手动或 tag 触发。产出 `eval/reports/<date>-baseline.md`
  （NL 结构通过率、修复率、p50/p95 延迟、模型与日期标注）。
- 修复集：`pytest tests/test_repair_dataset.py`，常规 CI。

## 6. 错误处理

- fixture 生成失败（解析缺口）→ 生成器测试失败，CI 红，不静默跳过。
- 锚点匹配失败 → 记 known-gaps，逐条人工判定：真缺陷（进
  bug 清单）/ 等价写法未覆盖（补等价表）/ MVP 匹配器过严（升级路径）。
- 真实模式模型不可达 → 脚本以明确错误退出，不产生半截报告。
- 录制 fixture 缺失 → 测试 skip 并在报告中标注，不视为通过。

## 7. 测试策略（对测试的测试）

- `tests/test_golden_set_gen.py`：生成器正确性（数量、唯一性、锚点非空）。
- `tests/test_anchor_match.py`：锚点匹配器单元测试——等价写法通过、
  丢算符检出、降级检出、子序列语义。
- `tests/test_golden_set.py`：录制模式黄金集（参数化 100 条）。
- `tests/test_repair_dataset.py`：修复集（参数化 50 条）。
- 真实模式脚本不进 pytest。

## 8. 验收门槛

1. 常规 CI：修复集 + 录制模式黄金集 + 生成器/匹配器测试全绿。
2. 基线报告产出两类数字，写入 README 与 comparison.md，带“开发集口径、
   非 general benchmark”声明（沿用 v0.4.1 先例）。
3. `git diff` 中无 `src/texada` 运行时行为变更。
4. known-gaps 清单建立，失败用例零静默。

## 9. 待验证事实（实现前须核实）

- 100 条表格解析覆盖率（一次性生成器测试保证，但需人工抽查 A–H 各类）。
- run_log store 的 run_id 落库断言路径（确认 `RunLogStore` 写入可在
  pytest 内以 tmp_path 触发）。
- 录制 turns 的 fixture 格式与 `FakePlanner` 接口匹配
  （`tests/test_agent_runtime.py` 现有模式）。
- `render_math` 在 pytest 内的可用性（进程内 KaTeX，无浏览器依赖）。
