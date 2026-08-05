# TeXada v0.3.2 技术报告

> 版本：v0.3.2
> 日期：2026-07-28
> 定位：基于端侧 Agent 的结构化数学编辑器
> 默认模型：MiniCPM5-1B（规划与文本）+ MiniCPM-V 4.6（视觉 OCR）

> 更新（2026-08-05）：本报告内容基线为 v0.3.2。当前 `main` 与桌面发布版本为
> 0.3.8；0.3.3–0.3.8 的变更以 CHANGELOG.md 为准。核心架构要点（双模型角色、
> 确定性工具边界、CAS 可选且未注册、桌面 sidecar 发布形态）自 v0.3.2 起
> 保持不变。v0.3.8 新增的输入安全护栏（嵌套深度上限、diff 规模降级、
> 工具执行超时）详见 CHANGELOG 与 `tests/test_safety_guards.py`。

## 1. 摘要

TeXada v0.3.0 完成了从“自然语言转 LaTeX 工具”到“端侧结构化数学编辑 Agent”的
架构升级。系统不再把一次模型输出当作最终结果，而是把自然语言、OCR 与公式补全
统一建模为：

```text
Input / Candidate
        ↓
MiniCPM5 Planner
        ↓
TeX Tool
        ↓
Observation / Semantic Document
        ↓
MiniCPM5 Planner or Runtime Guard
        ↓
Validated + Rendered Formula
```

本版本最重要的工程边界是：MiniCPM5-1B 只负责规划、工具选择、多步执行和有限的
文本生成；解析、编译校验、修复、语义比较、渲染和导出全部由确定性或可独立测试的
TeX 工具负责。MiniCPM-V 4.6 只负责从图片提出 OCR 候选。项目没有内置 TeX2TeX
模型，也没有第三个“公式修复模型”；`repair_tex` 是本地确定性语法修复工具。

v0.3.0 同时增加了可观察性和数据可迁移性：每次 NL、OCR、补全、兼容转换和校验
请求都有唯一 run ID，记录模型、耗时、token、工具调用、停止原因、成功或失败状态
以及 Agent trace；运行日志、结果历史、自定义预设和非敏感设置支持 schema-v2 JSON
导入导出。

v0.3.2 保持上述桌面产品行为不变，新增可选、未注册的 CAS 能力边界和可复现评测
门禁。它先回答“哪些有限标量结构能够被安全转换、比较或拒绝”，不把实验能力提前
包装成面向用户的通用数学证明功能。

## 2. 产品边界与设计原则

### 2.1 产品定义

TeXada 的目标不是替代完整 TeX 引擎，也不是提供通用浏览器或 Shell Agent。它专注于
桌面数学编辑闭环：

1. 接收自然语言、公式图片或不完整 LaTeX；
2. 形成可验证的公式候选；
3. 使用专业工具检查、修复和渲染；
4. 向用户展示公式、源码、Markdown 和执行轨迹；
5. 支持复制、恢复历史结果或在系统当前光标处键入。

### 2.2 两个模型角色

| 角色 | 默认模型 | 职责 | 明确不负责 |
|------|----------|------|------------|
| Planner / Text | `hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M` | 规划、工具选择、NL 候选、复杂补全、状态推进 | 直接修复非法 LaTeX、模拟工具结果 |
| Vision / OCR | `openbmb/minicpm-v4.6:latest` | 从图片提出 LaTeX 候选 | 最终校验、语义 Diff、渲染 |

Ollama 是默认本地运行时。OpenAI-compatible 配置是同一组 MiniCPM 模型的传输和部署
方式，可指向 vLLM、SGLang 或其他兼容端点；它不改变产品的双模型边界。

### 2.3 确定性优先

“Agent 化”不等于所有输入都必须调用模型。对于边界清晰、结果唯一的输入，规则比
1B 模型更快、更稳定，也更容易测试。v0.3.0 因此保留三层执行策略：

```text
Level -1  Deterministic Candidate
          高置信度结构直接形成候选，但仍调用 compile_tex / render_math

Level 0   SymbolEngine + Operator-Drift Guard
          锁定关键算符、积分阶数和结构锚点

Level 1   Semantic Unit + Semantic Diff
          在明确存在 before/after 公式时比较数学结构
```

自然语言本身不会被伪装成参考 AST。只有两个真实公式版本存在时，系统才计算结构
Diff，避免把“用户意图”和“模型输出”错误地当作同一种数据。

## 3. 系统架构

### 3.1 分层结构

```text
┌──────────────────────────────────────────────────────────────┐
│ Desktop UI                                                   │
│ NL · OCR · Completion · Presets · History · Run Logs        │
└────────────────────────────┬─────────────────────────────────┘
                             │ local HTTP
┌────────────────────────────▼─────────────────────────────────┐
│ FastAPI                                                      │
│ request validation · CORS · history/run-log correlation     │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│ TeXadaAgentRuntime                                           │
│ candidate intake · planner loop · tool router · circuit      │
│ breakers · final runtime guard · structured trace            │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
┌───────────────▼────────────────┐  ┌───────────▼──────────────┐
│ MiniCPM model boundary         │  │ TeX specialist tools     │
│ MiniCPM5-1B / MiniCPM-V 4.6   │  │ parse / compile / repair │
│ Ollama or compatible endpoint │  │ diff / render / export   │
└────────────────────────────────┘  └───────────┬──────────────┘
                                                │
                                    ┌───────────▼──────────────┐
                                    │ Semantic math layer      │
                                    │ pinned KaTeX 0.17.0 AST  │
                                    │ normalized units + diff  │
                                    └──────────────────────────┘
```

### 3.2 主要代码边界

| 模块 | 责任 |
|------|------|
| `agent/protocol.py` | 统一解析 MiniCPM5 原生 XML tool calling 与 OpenAI `tool_calls` |
| `agent/runtime.py` | Planner 循环、工具路由、Observation、熔断与最终状态 |
| `tools/registry.py` | 六个工具的 schema、实现与参数边界 |
| `semantic/katex.py` | 在可复用的进程内 V8 中运行固定版本 KaTeX |
| `semantic/parser.py` | 将 KaTeX AST 归一化为 Semantic Document |
| `semantic/diff.py` | 角色感知、加权、有序树对齐 |
| `core/candidates.py` | 高置信度 NL/显式 LaTeX 候选快速路径 |
| `core/operator_guard.py` | Level 0 算符存在性、积分阶梯与候选归一化 |
| `core/repair.py` | 无模型确定性修复服务 |
| `store/run_log.py` | 请求级运行账本、筛选、trace 详情和导入导出 |

## 4. Agent Runtime

### 4.1 Planner 协议

MiniCPM5 官方 XML tool calling 与 OpenAI-compatible 服务返回的结构化 `tool_calls`
最终都归一化为同一个 `PlannerTurn`：

```text
PlannerTurn
  ├── content
  ├── tool_calls[]
  │     ├── id
  │     ├── name
  │     └── arguments
  └── tokens_used
```

Tool Router 只接受注册过的工具名和 JSON 对象参数。未知工具、非法参数和工具内部
可预期异常都会转成结构化 Observation，而不是让整个服务进程崩溃。

### 4.2 执行状态机

一次 Agent 运行会维护：

- 当前候选 `latest_latex`；
- 当前 Semantic Document；
- 工具调用指纹集合；
- 连续工具错误数；
- 算符漂移重试次数；
- token 与延迟统计；
- 逐步 trace；
- 最终 `stop_reason`。

OCR 和补全首先执行 candidate intake：候选会先经过 `compile_tex`，其结果作为
第一条 Observation 交给 Planner。若候选非法，Planner 不能直接把自己生成的新字符串
冒充修复结果，必须调用 `repair_tex`。这一策略把“规划”和“专业修复”从运行时层面
真正分开。

### 4.3 有界循环和熔断

默认最大 Planner 步数为 3，可配置范围为 1～8。运行时还包含：

- 重复工具调用指纹熔断；
- 连续两次工具错误截断；
- 算符漂移重试上限；
- 推理请求超时和 API 请求超时；
- 空输出与缺少最终候选的安全回退；
- 成功 `render_math` 后立即收敛；
- 最终 compile/render guard。

常见停止原因包括：

| Stop reason | 含义 |
|-------------|------|
| `deterministic_candidate` | 高置信度候选通过工具校验和渲染 |
| `render_confirmed` | Planner 调用渲染工具后完成 |
| `planner_final` | Planner 返回最终裸 LaTeX，运行时完成终检 |
| `operator_drift_deterministic_restore` | 运行时按权威锚点恢复结构 |
| `repeated_tool_call` | 重复工具调用被熔断 |
| `tool_error_limit` | 连续工具错误达到上限 |
| `max_steps_or_empty_final` | 达到步数上限或没有可用最终候选 |

## 5. TeX 专业工具

### 5.1 六个单一职责工具

| 工具 | 输入 | 输出 |
|------|------|------|
| `parse_tex` | LaTeX | Semantic Document、诊断信息 |
| `compile_tex` | LaTeX | 语法有效性、诊断、Semantic Document |
| `repair_tex` | 非法 LaTeX | 确定性修复结果、复验结果、Semantic Diff |
| `semantic_diff` | before / after | 结构变化、加权距离、相似度 |
| `render_math` | LaTeX / mode | KaTeX HTML 或纯 LaTeX 渲染结果 |
| `export` | LaTeX / format | LaTeX 或 Markdown 导出文本 |

工具最大输入长度和参数 schema 都由 Tool Router 统一约束。每次执行返回耗时、成功
状态、输出或错误，形成 Planner 可消费、日志可持久化、UI 可展示的 Observation。

### 5.2 校验与修复

`compile_tex` 组合多层校验：

1. 内容门禁；
2. 花括号、方括号与环境配对；
3. 命令和结构检查；
4. 固定版本 KaTeX 解析；
5. Semantic Document 生成。

`repair_tex` 只做安全、局部、可复现的语法修复，例如闭合括号、环境和常见转义
归一化。它不会猜测缺失的数学推导，也不会调用 MiniCPM 或隐藏模型。

## 6. Semantic Unit 与 Semantic Diff

### 6.1 为什么不是字符串 Diff

以下两类变化需要区别：

- 空格、包装方式或无关渲染细节变化；
- 分子、分母、根号内容、积分上下界、上下标等数学角色变化。

字符串 Diff 无法可靠表达第二类变化。TeXada 把固定 KaTeX AST 归一化为数学语义
单元，常见 kind 包括：

```text
fraction · numerator · denominator
root · radicand · index
integral · lower_bound · upper_bound
summation · product · limit
script · subscript · superscript
environment · row · cell
symbol · number · command
```

### 6.2 角色感知加权对齐

Semantic Differ 先按稳定数学角色匹配唯一子节点，再用动态规划对齐剩余有序子节点。
分式、积分、根式、环境等结构拥有更高权重；分子、分母、根号内容、积分上下界和
上下标被标记为关键角色。相同子树通过 fingerprint 直接剪枝。

输出不仅包含一个距离数字，还包含可解释变化：

```text
operation · path · unit_kind · role · before · after · cost
```

这使 Diff 既能进入 Agent Observation，也能作为后续评估、数据构建或训练 reward 的
基础。但在 v0.3.0 中，它服务于显式公式变更，不承担“理解任意自然语言意图”的职责。

## 7. 三条产品输入路径

### 7.1 自然语言

```text
NL
 → DeterministicCandidateEngine?
   → yes: compile_tex → render_math → final
   → no: SymbolEngine anchors → MiniCPM5 Planner → tools → final guard
```

高置信度路径覆盖区间求和、商式极限、偏导、多重积分、简单分式与运算、组合幂、
根式和显式行内 LaTeX。句末标点以及“加上”“乘以”“趋近于”等常见中文表达会先
归一化。候选即使不调用 Planner，仍必须经过 `compile_tex` 与 `render_math`，因此
结果保留真实工具轨迹，而不是绕开 Agent 质量门禁。

### 7.2 OCR

```text
Image
 → MiniCPM-V 4.6 candidate
 → escaping normalization
 → candidate intake / compile_tex
 → MiniCPM5 review
 → repair_tex when required
 → render_math
```

视觉模型返回空内容时，OCR 会检查 reasoning 字段并进行一次有界重试；仍为空则返回
明确的服务错误。运行日志只保存文件名、MIME、字节数和执行信息，不保存图片原始字节。

### 7.3 补全

常见前缀如 `\alp`、`\sum`、`\frac{`、`\sqrt{`、`\int` 和可安全闭合的残缺结构
优先使用本地规则。确定性补全以 0 token 形成候选，再通过 compile/render 工具路径。
规则无法判断时才调用 MiniCPM5，随后仍进入统一 Agent Runtime。

## 8. 可观察性与数据系统

### 8.1 Request Ledger

运行日志以唯一 `run_id` 记录：

- operation 与 input type；
- 输入文本或 OCR 文件元数据；
- Planner/OCR 模型名称与后端；
- HTTP 成功状态和公式有效性；
- 输出 LaTeX、intent、source；
- 延迟、token、工具次数和工具名；
- stop reason；
- 完整 trace 或错误信息。

“请求成功”和“公式有效”是两个独立状态。失败请求同样写入日志，但不会伪造成功的
结果历史。成功结果通过 `run_id` 与 HistoryStore 关联。

### 8.2 导入导出

schema-v2 完整备份包含：

```text
_meta
settings          # 非敏感配置
shorthands        # 用户预设
history           # 成功结果
run_logs          # 成功与失败的请求账本
```

API Key 和 OCR 原图不会被导出。历史、运行日志和自定义预设也支持独立 JSON
导入导出；默认 merge 并去重，replace 模式只在用户明确选择时使用。

## 9. 性能与质量结果

### 9.1 本地实测

测试环境为本地 Ollama 与项目默认 MiniCPM 模型。端侧模型延迟受设备、模型冷热状态
和采样影响，因此以下数值用于说明路径差异，而不是跨设备基准：

| 场景 | 结果 |
|------|------|
| 高置信度 NL API 热路径 | 约 5～25 ms，0 token |
| 带标点/同义词 NL UI 代表用例 | 约 142.2 ms |
| `求k从1到n的k平方` | 稳定输出 `\sum_{k=1}^{n} k^2` |
| 补全 `x+\alp` | 输出 `x+\alpha`，1 步 / 2 次工具调用 / 0 token |
| OCR 积分图片 | 正确输出积分公式，后端记录约 3.6～10.1 秒 |
| API 黑盒矩阵 | 32 个正常与非法输入合约符合预期 |

### 9.2 自动化质量门禁

v0.3.0 发布基线本地验证：

- 189 个离线测试通过；
- 8 个 live E2E 在默认测试中按设计跳过；
- Ruff 通过；
- JavaScript 语法检查通过；
- Cargo fmt/check 通过；
- `uv lock --check` 与版本一致性测试通过；
- npm 官方 registry 审计为 0 vulnerabilities；
- `pip-audit --strict` 未发现已知漏洞；
- wheel 构建成功并包含固定 KaTeX V8 资源；
- sidecar stub 与 Tauri `externalBin` 检查通过；
- OpenAPI 版本为 `0.3.2`。

v0.3.2 的增量发布门禁为：

- 全仓 281 项测试通过，8 项 live E2E 按设计跳过；
- CAS 定向 35 项连续运行五轮全部通过；
- `.equals() == False`、非有限对象、seed 与 assumptions 均有机器可读 fixture；
- `algebra_check` 未注册，默认 sidecar 不打包 CAS 可选依赖；
- Ruff、`git diff --check` 与生成文档同步检查通过。

正式 tag 还会触发 GitHub Actions，在 macOS ARM、macOS Intel 和 Windows x64 上重新
执行审计、构建 PyInstaller FastAPI sidecar、生成安装包，并对 macOS DMG 进行
Developer ID 签名、notarization 和 staple。

## 10. 安全与部署

### 10.1 本地网络边界

桌面端默认连接 `127.0.0.1:18732` 的 TeXada FastAPI sidecar；后端再连接默认
`localhost:11434/v1` 的 Ollama。两者是不同服务层。API 绑定 loopback，CORS 只允许
开发地址和 Tauri 本地 origin。

### 10.2 输入和密钥

- OCR 上传限制 MIME 和最大字节数；
- API 请求使用 Pydantic schema 校验；
- 工具名和参数由 Tool Router 白名单约束；
- 配置更新先完整校验，再原子写入；
- 配置文件权限收紧为当前用户可读写；
- API Key 不进入备份和运行日志；
- Agent 有步数、重复调用、错误次数和超时上限。

### 10.3 桌面发行

安装包内置 FastAPI sidecar，普通用户不需要单独安装 Python、Node 或 Rust。Ollama
或兼容 MiniCPM endpoint 仍需由用户提供。发行矩阵为：

| 平台 | 产物 |
|------|------|
| macOS Apple Silicon | `TeXada_0.3.2_aarch64.dmg` |
| macOS Intel | `TeXada_0.3.2_x64.dmg` |
| Windows x64 | `TeXada_0.3.2_x64-setup.exe` |

## 11. 已知限制

1. LaTeX 有效不等于数学命题正确。例如 `a/0` 可以通过语法校验，但数学上无定义；
   数学语义检查应作为独立工具设计，不能混入语法 Validator。
2. 不符合高置信度规则的开放式 NL 仍依赖 1B Planner，延迟和输出具有采样波动。
3. OCR 准确率和延迟受图片质量、视觉模型冷热状态与设备性能影响。
4. KaTeX 是渲染导向解析器，不是完整 TeX 宏展开引擎；任意自定义宏和宏包不在当前
   兼容目标内。
5. Semantic Diff 当前关注结构变化，不声称证明两个数学表达式代数等价。
6. v0.3.2 的 CAS 代码是可选、未注册的能力与评测骨架，不进入 Agent、API、桌面
   UI 或默认 sidecar；只有通过白名单的有限标量子集才进入受控比较。
6. macOS 光标处键入需要辅助功能权限；签名和 notarization 依赖仓库发布 secrets。

## 12. 后续方向

- 增加矩阵、分段函数、复杂积分域和多行环境 fixture corpus；
- 为数学定义域、除零和维度一致性增加独立 semantic-check 工具；
- 统计真实运行日志中的 stop reason、工具错误和常见修复模式；
- 将高频失败 case 转成确定性规则、Semantic Unit fixture 或训练数据；
- 为 Semantic schema 增加显式版本与迁移策略；
- 继续缩短 OCR 候选到最终渲染之间的 Planner 开销；
- 保持 TeX2TeX 等研究模型与产品 Agent Runtime 解耦，在独立仓库迭代。

## 13. 结论

TeXada v0.3.2 延续 v0.3.0 的核心技术价值：不是“让一个小模型生成 LaTeX”，而是
用清晰边界把小模型变成可控 Planner。确定性规则负责高置信度输入，专业工具负责
数学编辑操作，Semantic Unit 负责结构状态，Runtime Guard 负责失败上限，Run
Ledger 负责可观察性与复现；新增 CAS 骨架则示范了专业能力必须先有可审计边界，
再进入产品工具层。

这一架构在只保留 MiniCPM5-1B 和 MiniCPM-V 4.6 两个模型角色的前提下，同时获得了
端侧部署、低成本快速路径、可解释工具轨迹和可持续扩展的数学结构层。它构成了
TeXada 后续数据闭环、专业工具扩展和端侧数学 Agent 研究的发布基线。
