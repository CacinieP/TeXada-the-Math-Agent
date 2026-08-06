# TeXada 设计思路与版本迭代 Diff

> 文档定位：这不是一份只描述当前代码的模块清单，而是一份解释 TeXada 为什么会
> 变成今天这样、每一代方案解决了什么问题、又留下了什么新问题的设计演化记录。
> 文中将“已经发布并有仓库证据的事实”“标签前的工程阶段”“v0.3.0
> 发布基线”明确分开，避免用事后的架构语言重写历史。

## 0. 文档范围、事实边界与阅读方式

TeXada 的仓库历史并不是一条从“传统输入法”直线走向“Agent”的简单路径。它至少
经历了四次产品身份变化：

1. 最初是一个“确定性模板 + 通用小模型”的自然语言转 LaTeX 命令行原型；
2. 随后被重构为具有 API、路由、校验、修复、存储和桌面壳的本地数学生产力工具；
3. 在 MiniCPM5-1B 的能力边界下，形成了“上游锁定关键信息、下游确定性兜底”的
   务实管线，并加入 Operator-Drift Guard；
4. 在本地 v0.3.0 中，项目才真正开始具备 Planner、专业工具、Observation、
   Semantic Unit 与 Semantic Diff，并最终明确产品只保留 MiniCPM5-1B 和
   MiniCPM-V 4.6 两个模型角色。

仓库存在的正式标签为 `v0.1.0`、`v0.2.0`、`v0.2.1`、`v0.2.2`、
`v0.2.3`、`v0.2.4`、`v0.2.6` 与 `v0.3.0`～`v0.3.7`。`v0.2.5` 有明确的
release commit 和 CHANGELOG 记录，但没有独立 Git tag；`v0.3.8` 同样已有
release commit（`Release v0.3.8 with safety and robustness fixes`）与
CHANGELOG 条目，但尚未打 tag。因此，本文把它们作为真实发布阶段讨论，同时
不会声称仓库存在并不存在的 `v0.2.5`、`v0.3.8` 标签。`v0.3.0` 指相对于
`v0.2.6` 建立的端侧 Agent 发布基线。

本文所说的“版本 Diff”不只指代码行数变化。更重要的是五种设计差异：

- **产品 Diff**：用户究竟把 TeXada 当作什么；
- **职责 Diff**：模型、规则、工具、UI 各自负责什么；
- **状态 Diff**：系统内部传递的是字符串、结果对象，还是 Semantic Document；
- **失败处理 Diff**：失败后是报错、修字符串、重试模型，还是重新规划；
- **工程 Diff**：依赖、打包、测试、数据持久化和发布方式怎样变化。

如果只关心当前实现，可直接阅读第 5～10 节；如果要理解为什么没有直接采用
DeepDiff、zss 或“让 LLM 一次做完”，应从第 2 节开始；如果要规划后续版本，应重点
阅读第 12～15 节。

---

## 1. 产品问题：TeXada 真正要解决的不是“少敲几个反斜杠”

传统 LaTeX 输入法的中心是字符：用户知道自己要写 `\frac`、`\int`、`\sum`，
系统只需要帮助补全命令、插入括号或提供符号面板。TeXada 面对的用户任务更复杂：

- 用户可能只知道自然语言里的数学意图，不知道 LaTeX 命令；
- 用户可能从截图、手写笔记或课件中获取公式；
- 用户可能拿到一段结构不完整、环境未闭合的 LaTeX；
- 用户需要的不只是一个字符串，而是可验证、可渲染、可复制、可再次编辑的公式；
- 用户更关心“分母有没有变”“积分上下界有没有丢”，而不是第 17 个字符是否不同。

这意味着 TeXada 的产品核心不应被定义成“自然语言到字符串的翻译器”。一个只做
`OCR → LLM → Render` 的系统，在正常样例里看起来足够聪明，但一旦输出错误，它
无法回答三个关键问题：

1. 错误来自识别、生成、语法、结构还是渲染？
2. 系统应该重试哪一步，而不是把全部工作重新做一遍？
3. 修改后的公式与修改前相比，数学结构到底发生了什么变化？

因此，v0.3.0 的定位是：

> **TeXada 是一个基于端侧 Agent 的结构化数学编辑器，而不是传统 LaTeX 输入法，
> 也不是一个把通用聊天模型包在输入框后面的演示。**

“结构化”一词有两层含义。第一层是软件结构化：Planner、Tool、Observation、
Validator、Renderer 各自有清晰边界。第二层是数学结构化：系统理解 fraction、
numerator、denominator、integral、lower bound、upper bound、subscript、
superscript、matrix row 和 matrix cell，而不是只理解反斜杠和花括号。

这个定位同时划定了不做的事情。TeXada 不试图成为完整 TeX 引擎，不试图解释任意
宏包，不试图做通用数学证明 Agent，也不把“兼容所有模型”作为当前目标。它首先要
在端侧、小模型、常用数学表达和桌面编辑闭环里做到可靠。

---

## 2. 总体设计哲学

### 2.1 确定性优先，但不等于拒绝 Agent

TeXada 从早期版本起就有一个正确判断：能用确定性代码解决的问题，不应交给小模型
猜测。意图分类、中文术语预翻译、快捷公式查找、括号平衡、环境配对、渲染模式切换
都属于这种任务。确定性路径的优点不仅是快，更重要的是可测试、可解释、可复现。

但“确定性优先”不应被误解为系统永远只能是一条固定流水线。固定流水线的问题是，
不同输入需要的步骤不同：合法公式无需修复，畸形公式需要确定性 Fixer，纯导出无需
OCR，结构编辑需要 before/after Diff。Agent 的价值不是取代确定性模块，而是选择
何时调用哪个确定性模块，并根据 Observation 决定是否继续。

因此，当前哲学可以概括为：

```text
模型负责不确定的决策；
工具负责确定的专业动作；
运行时负责边界、状态和停止条件；
数据结构负责让每一步的结果可比较。
```

### 2.2 小模型不是缩小版的大模型

1B 端侧模型的限制决定了运行时必须比云侧大模型更“硬”。它容易产生以下问题：

- 工具调用 XML 或 JSON 格式错误；
- 重复调用同一个工具；
- 收到错误 Observation 后继续原计划；
- 长上下文中忘记用户最初要求的算符；
- 在多轮工具调用中不断增加反斜杠转义；
- 迟迟不输出 final answer；
- 用自然语言解释代替裸 LaTeX。

因此，TeXada 不能只写一个 prompt 然后相信模型自我约束。运行时必须限制最多三轮
Planner step，记录规范化后的工具调用指纹，阻断重复调用，并在连续两次工具错误后
熔断。即使 Planner 失败，最终 runtime guard 仍会执行 compile、必要时 repair，
然后 render。换言之，模型可以建议下一步，但不能绕过系统不变量。

### 2.3 专业能力必须下沉到工具

MiniCPM5-1B 不负责直接修复非法公式。它可以识别“需要修复”，但真正的语法修复由
确定性的 `repair_tex` 完成。类似地，模型不应凭想象判断公式是否可编译，而应调用
`compile_tex`；不应口头描述结构差异，而应调用 `semantic_diff`。

这种职责分离带来三个长期收益：

1. 公式修复无需加载第三个模型，可完全由无模型单元测试覆盖；
2. MiniCPM5-1B 与 MiniCPM-V 4.6 的职责不会被额外 checkpoint 模糊；
3. Planner 的好坏不再决定校验、修复和渲染工具的可靠性。

### 2.4 深度绑定 MiniCPM5，但保留窄接口

战略上，TeXada 选择 MiniCPM5-1B 作为端侧 Planner，不承诺任意 OpenAI-compatible
模型都能复现相同行为。运行时直接兼容 MiniCPM5 的原生 XML function 格式，同时
也接受服务端已归一化的 OpenAI `tool_calls`。这叫“协议事实上的深度绑定”。

代码上仍保留 `PlannerBackend` 窄接口，只暴露 `plan`、`generate_latex` 和
`extract_latex`。这不是为了建设一个抽象到失去意义的通用 Agent 框架，而是为了
防止 MiniCPM 客户端细节渗透到工具层。未来更换 MiniCPM 的部署方式时，只需更换
一个传输实现，不需要重写 Semantic Parser、确定性 Fixer 或 UI。

### 2.5 先保证可恢复，再追求“看起来聪明”

设计优先级依次为：

1. 用户数据不丢失；
2. 最终公式可验证、可复制；
3. 失败路径可观察；
4. 常见公式结构正确；
5. 推理步骤漂亮；
6. 覆盖更多模型与宏包。

这解释了为什么 v0.2.6 先做备份与导入，为什么 v0.3.0 先做 trace、熔断和工具边界，
而不是先增加一个更复杂的自治循环。可靠的本地工具应允许用户看到失败并继续工作，
而不是在后台无限重试。

### 2.6 确定性工具也必须资源有界

“确定性优先”不等于“确定性天然安全”。确定性只保证结果可重复，并不保证计算
有界：Parser 的递归深度、Semantic Diff 的 O(m·n) 对齐矩阵、Serializer 的
递归输出，都只由输入决定，而输入正是模型生成的、不可信任的。

v0.3.0 对 Agent 行为设置了完整预算——Planner 最多三轮、重复工具调用阻断、
连续错误熔断、未知工具与非法参数拒绝、4000 字符上限、最终强制 compile/render——
但默认把 Parser、Diff、Serializer 这些“确定性模块”当作天然可靠。v0.3.8 的实测
推翻了这一假设：3151 字符的合法 `\frac` 链可以击穿 V8、fallback parser 与递归
serializer；1200 节点的平铺公式让 O(m·n) Diff 运行约 65 秒；2000 节点直接触发
SIGBUS。schema 有限、输入长度有限，并不等于计算复杂度有限、递归深度有限。

因此设计哲学补上第六条：

```text
所有处理模型生成输入的确定性工具，也必须具备显式的时间、空间和结构预算；
超限时返回显式降级结果，不继续追求精确计算。
```

这与 CAS 子系统的既有做法（父进程 timeout + PID-RSS 限额）是一致的敌对输入
意识：威胁模型不能只覆盖“Agent 失控”，还要覆盖“确定性工具失控”。

---

## 3. 标签前阶段：从原型到可发布产品

### 3.1 2026-06-04 初始原型：模板、Gemma 与单进程 CLI

最初提交的产品描述是“Local math formula agent powered by Gemma 4 E4B”。核心
代码集中在 `agent.py`、`main.py` 和 `symbol_dict.py`。主流程为：

```text
输入
  → shorthand 展开
  → 精确模板匹配
  → Gemma/Ollama 生成
  → 花括号与 begin/end 基础校验
  → 终端显示
```

这一阶段的正确之处是很早就形成了“确定性模板先于模型”的思想，而且低温度、裸
LaTeX 输出、去除 `$` 和 Markdown fence 等约束都已经存在。它证明了产品需求成立：
自然语言确实可以降低公式录入门槛。

但它有明显的结构问题：

- `TeXadaAgent` 同时负责路由、模型调用、结果清洗和校验；
- 结果状态只有 `ConversionResult`，没有可组合的工具 Observation；
- 校验只能发现字符串级语法问题，无法定位数学结构；
- CLI 是唯一稳定入口，桌面、历史、OCR 都只是愿景；
- 模型被固定为 Gemma，模型管理与业务逻辑耦合；
- “Agent”更多是产品命名，尚不存在规划与工具循环。

这一阶段到 v2 重构的 Diff 规模为约 3353 行新增，主要不是业务功能，而是设计文档、
UI mockup、Python 包骨架和 v1 archive。其真正意义是承认原型不适合作为长期地基。

### 3.2 2026-06-08 v2 设计：先定义能力边界，再写 M0

v2 设计文档提出了一个影响后续所有版本的判断：

> 小模型不是缩小版的 70B；应通过规则、模板和严格校验降低它需要完成的任务难度。

设计中已经明确 Input Router、Intent Classifier、Symbol Engine、推理层、Composer、
Validation Layer、OCR Pipeline、Shorthand、History 与平台输出等模块。虽然其中
一些预测能力和性能预算后来并未完全实现，但模块边界是重要资产。

从 v2 设计到 M0 骨架，仓库约 40 个文件变化、3312 行新增、452 行删除。根目录的
单文件原型被移除，代码进入 `src/texada/`；FastAPI、配置、路由、修复、渲染、
存储、类型和测试成为一等模块。这个 Diff 的本质不是“代码变多”，而是将系统从
一个函数调用改造成可替换的管线：

```text
原来：TeXadaAgent.convert() 包办全部工作
后来：InputRouter 调度 Intent/Symbol/Model/Validator/Fixer/Renderer/Store
```

M0 的一个重要遗产是测试文化。Intent、Symbol、Validator、Fixer、Highlighter 和
Render 都有无模型测试。这为后来更换模型、桌面壳和 API 提供了安全网。

### 3.3 Gemma → MiniCPM，llama.cpp → Ollama

2026-06-12 到 06-13 期间，项目经历了两次推理基础设施转向。第一次从 Gemma 迁移
到 MiniCPM，并尝试 llama.cpp 本地管理；第二次又删除专门的 llama manager 和旧
Ollama manager，统一成纯 Ollama/OpenAI-compatible 后端。

从 M0 到 MiniCPM/llama.cpp 阶段，变化涉及约 57 个文件、9641 行新增。除了模型层，
还出现了 Tauri、Swift shell、图标、启动脚本、依赖锁和更多测试。这说明模型迁移
并不是一个孤立 `model_name` 变更，它会影响安装、资源管理、超时、输出字段与桌面
生命周期。

随后从 llama.cpp 到纯 Ollama，约 18 个文件变化、863 行新增、570 行删除。其设计
判断是：TeXada 不应同时维护模型格式、进程生命周期和推理协议。把本地模型交给
Ollama 管理后，TeXada 只需要关心 endpoint、model name、readiness 和 OpenAI 风格
消息。收益包括：

- 本地与云侧共享一个客户端抽象；
- 文本 MiniCPM5 与视觉 MiniCPM-V 可配置为不同模型；
- 自定义 Ollama 端口和远程 endpoint 成为配置问题；
- 安装包不需要内置完整推理引擎。

代价是工具调用能力受推理服务支持情况影响。历史技术报告因此一度写下“移除 Native
Function Calling”，当时的正确策略是纯 chat + 后处理。v0.3.0 恢复 tool calling，
并不是否定当时判断，而是因为 MiniCPM5 的官方 Agent 能力和服务端解析能力已经成为
新的可用条件。

### 3.4 Operator-Drift Guard：第一个真正针对 1B 模型的产品保护

2026-06-17 的回归案例非常典型：用户输入“二重积分”，SymbolEngine 已经将其变为
`\iint`，但模型受 few-shot 干扰输出了普通 `\int`，甚至回答成另一个积分问题。
语法校验会认为输出完全合法，因此 Validator 无法发现“答错题”。

Operator-Drift Guard 的实现非常小：

- 积分族按 `\int → \oint → \iint → \iiint` 建立阶梯；
- 输出等级低于输入等级，视为漂移；
- `\sum`、`\prod`、`\lim`、`\frac`、`\partial` 只检查是否丢失；
- 升级不算漂移，空输出交给模型层的另一条重试路径；
- 漂移时只做一次带硬约束的受控重试；
- 重试仍漂移时不盲目替换第一次结果。

这不是 Semantic Diff，也不是 AST 比较，本质就是子串查找和整数等级比较。但它是
一个非常成熟的局部设计，因为它精确解决了“合法但语义关键算符丢失”的问题，成本
几乎为零，误报面可控。v0.3.0 的正确做法不是删掉它，而是把它提取成共享的
`OperatorDriftGuard`，同时供旧 `InputRouter` 和新 Agent Runtime 使用。

---

## 4. 正式版本逐代 Diff

### 4.1 v0.1.0：从开发工程变成可交付桌面产品

`v0.1.0` 的核心不是某个公式算法，而是“软件能否被普通用户安装和运行”。它发布
Tauri 桌面壳、macOS DMG、Windows NSIS、本地 Ollama 默认配置、云侧兼容模式、
自然语言、OCR、补全、预设、历史、校验、修复、渲染、复制和光标处键入。

从漂移守卫阶段到 `v0.1.0` 的仓库 Diff 很大：约 106 个文件变化，既有 11516 行
新增，也有 10777 行删除。大量删除不是功能倒退，而是一次“发布面收敛”：

- 删除重复的 Swift shell、根目录 `.app`、LaunchAgent 和旧启动脚本；
- Tauri 成为唯一桌面壳；
- Python 后端被打成 sidecar，由桌面壳管理；
- 增加 audit 与 release workflow；
- 增加签名、公证、社区文件、文档索引和文件清单；
- 移除未被正式产品路径使用的平台适配层。

这一版建立了一个关键工程原则：仓库只能有一个当前产品面。原型、重复 shell 和历史
设计不能与正式入口并列，否则每一次修复都要回答“到底修哪一个”。

### 4.2 v0.2.0：历史记录从“日志”变成“可复用工作资产”

`v0.2.0` 从 `v0.1.0` 演进约 19 个文件、545 行新增、73 行删除。重点是历史记录：

- 可搜索自然语言、补全、OCR 与 LaTeX；
- 支持按类型筛选；
- 单条记录可以复用输入、复制 LaTeX、复制 Markdown；
- 查询覆盖 input、latex、intent 和 source；
- 清理同时遵守保留天数和最大条数。

设计层面的变化是：History 不再只是审计日志，而是编辑器状态的一部分。用户保存的
不是“模型曾经说过什么”，而是一个可以重新打开、再次插入、再次编辑的数学结果。
这为 v0.2.4 的“结果恢复”和 v0.2.6 的“数据备份”打下基础。

### 4.3 v0.2.1：渲染从开发机依赖变成离线产品资源

`v0.2.1` 的 Diff 看似涉及 83 个文件，但大部分是 vendored KaTeX 字体、CSS、JS 和
许可证。核心问题是：开发机有 `npx katex`，打包后的用户机器不一定有 Node。若后端
把 KaTeX CLI 缺失当成用户错误，产品会在安装成功后显示“无法渲染”。

这一版采取双层策略：

- 前端随 Tauri 打包完整 KaTeX 浏览器资源，核心显示不依赖外部网络；
- 后端使用 `npx --no-install`，不可用时返回明确的可见 fallback；
- OCR 与 completion 统一走相同渲染路径；
- Validator 对缺失或超时的可选 KaTeX CLI 做“跳过”而非误判系统崩溃。

设计思路是区分“公式无效”和“可选验证器不可用”。依赖缺失不能被伪装成公式错误，
也不能让整个请求失败。v0.3.0 进一步复用了这份已 vendored 的 KaTeX JS，使其成为
Semantic Parser、Validator 与后端 Renderer 的共同底层；当前工作区已经不再在请求
路径中启动 `npx`。前后端还共享 `\placeholder → \square` 宏策略，避免后端判定
Valid、前端却显示未知命令。V8 context 在 FastAPI lifespan 结束时显式关闭，服务
停止后不会残留后台进程。这里的 `npx` 描述只属于 v0.2.1 的历史实现。

### 4.4 v0.2.2：Preset 不再伪装成自然语言请求

`v0.2.2` 约 18 个文件变化、177 行新增、67 行删除。旧 shortcuts tab 会把快捷键
再次送入自然语言转换，这既浪费模型时间，也可能让确定性公式被模型改坏。新设计把
它改名为 Presets，并规定：

- 预设卡片直接插入公式；
- 每个预设独立提供 LaTeX 与 Markdown 复制；
- 卡片展示内联 KaTeX preview；
- 只有用户真正输入自然语言时才调用模型。

这是“确定性优先”在 UI 层的落实。系统不能在后端强调查表零模型，却在前端把查表
结果重新发给 LLM。

### 4.5 v0.2.3：视觉设计也是架构的一部分

`v0.2.3` 约 22 个文件变化、115 行新增、84 行删除，主要是深蓝主题、统一图标与多
平台资源再生成。它没有改变模型或 API，却解决了两个长期问题：

1. 不同平台、安装包和浏览器开发页使用不同图标，产品身份不一致；
2. 透明无边框浮窗如果缺乏清晰层级，用户难以判断可拖动区、输入区和结果区。

因此视觉 Diff 不能被简单归类为“皮肤”。桌面工具的窗口拖动、焦点、IME、安全点击
区、可交互卡片边界都与视觉结构耦合。后来 v0.2.5 的圆角与 inset 修复，也是对这个
结构的继续收敛。

### 4.6 v0.2.4：恢复结果与复用输入是两种不同语义

`v0.2.4` 约 15 个文件变化、106 行新增、37 行删除。修复前，点击历史记录可能把
旧输入重新送给模型，导致用户明明选择的是过去结果，却得到一次新的随机生成。修复
后：

- 点击记录直接恢复过去的 LaTeX 结果；
- “复用输入”保留为独立动作；
- 复制动作始终复制已保存结果。

这个 Diff 看似是 UI bug，实际上是事件语义设计：`open_result` 与 `reuse_input`
不能共用一个动作。它也预示了 Semantic Unit 编辑器未来需要区分“读取状态”“从状态
发起新任务”和“原地修改状态”。

### 4.7 v0.2.5：连续 OCR 与桌面壳稳定性

`v0.2.5` 对应 release commit，约 15 个文件变化、191 行新增、72 行删除，但仓库
没有独立 tag。本版修复：

- 一次 OCR 完成后，可立即拖入、粘贴或选择下一张图片；
- 避免反复进入 OCR tab 后重复注册事件；
- 桌面壳默认可见；
- 无边框窗口通过 inset 和 clip 改善圆角；
- macOS Intel sidecar 改为 PyInstaller 完成后统一签名。

设计上，这是从“单次 demo 成功”走向“连续使用稳定”。E2E 不应只测试一次请求，
还要测试第二次拖图、重复打开 tab、窗口重新显示和多架构打包。

### 4.8 v0.2.6：本地优先必须包含数据主权

从 v0.2.5 到 `v0.2.6` 约 19 个文件变化、969 行新增、66 行删除。核心是完整备份：

- 全量备份与仅历史备份；
- merge 导入时去重；
- replace 模式；
- 自定义预设导入导出；
- 非敏感设置导出；
- API Key 明确排除；
- 清空历史需要确认；
- OCR 粘贴提示按平台显示 Cmd/Ctrl。

“本地优先”不能只意味着模型在本机运行，还应意味着用户能导出、迁移和恢复自己的
数据。v0.2.6 将 History、Preset、Settings 从内部实现提升为有稳定 JSON 合约的用户
资产。这也是为什么 v0.3.0 不应随意改变这些旧 API；新 `/api/agent` 被加入主路径，
旧 `/api/convert` 仍作为兼容入口保留。

### 4.9 v0.3.1～v0.3.8：发布后的收敛、打包与安全补章

v0.3.0 之后正式标签按约两天一版的节奏推进，每一版都是“某个真实故障被复现、
修复并被测试固化”：

- **v0.3.1**：零模型补全（裸上下标、空参数、空上下界、尾部运算符的
  `\placeholder{}` 占位槽）、唯一匹配命令拼写的保守纠错，以及“非候选工具不能
  替换公式状态”的 Runtime 硬化；200 条 NL + 200 条补全桌面审计沉淀出 59 条
  定向回归。
- **v0.3.2**：CAS 能力门。可选、未注册的 `src/texada/cas/` 骨架、白名单
  SymPy 翻译器、证据等级与 PID-RSS 限额的隔离 worker。详见 §12.5，产品行为
  未改变。
- **v0.3.3**：桌面可靠性收敛。修复 v0.3.1 引入的 Agent 收尾回归（修复后仍
  无效的候选不再变成 HTTP 503，而是返回结构化 `valid=false` 与
  `validation_failed_after_repair`）；修复 PyInstaller 漏打包 MiniRacer 原生库
  与 ICU 数据导致 sidecar 报告 `KaTeX parser unavailable`；修复 Tauri 桥接
  未暴露导致已运行后端显示 `No API`；新增零 token 确定性候选（二重/三重积分、
  分段函数）。
- **v0.3.4**：macOS Hardened Runtime 崩溃修复。公证 DMG 首次 KaTeX 请求触发
  `Failed to reserve virtual memory for CodeRange`；sidecar 入口改带
  `allow-jit` 与 `allow-unsigned-executable-memory` 权限签名，并新增发布门禁：
  检查签名 entitlements 并对冻结 sidecar 执行真实零 token Agent 请求。
- **v0.3.5**：桌面桥接把回环 FastAPI 请求送进操作系统代理，健康后端被显示为
  `No API`、公式请求 502。Tauri 客户端对 localhost/回环地址禁用代理发现，并
  用 Rust 回归测试固化。
- **v0.3.6**：移除窗口聚焦时自动读取剪贴板与预填输入框，避免 `ollama pull ...`
  之类命令误入公式框；冷启动 `No API` 改为 `Starting API…`。
- **v0.3.7**：从 GPL 重授权为 AGPL-3.0-or-later 并同步全部元数据；未发布源码
  版本推进到 0.3.7，避免与 GPL 的 v0.3.6 标签混淆；桌面启动探测改短 HTTP
  超时 + 60 秒截止，移除重复状态请求。
- **v0.3.8**：安全补章（详见 §2.6、§6.7、§7.2、§8.4 与 §12.6）。为三条经
  实测确认、普通输入即可触发的故障路径加边界：深嵌套公式（3151 字符合法
  `\frac` 链曾使进程崩溃或挂死）、超大 `semantic_diff`（O(m·n) 对齐 n=1200
  约 65 秒、n=2000 内存耗尽）、无执行上限的工具调用；同时重写 `SymbolEngine`
  为单遍最长匹配，修复 `argmax` 二次转义与“向量空间”误替换。

这一段的总体 Diff 是：Agent 发布后，问题不再来自“缺功能”，而来自“功能在
真实安装、真实输入下如何失败”。每个故障都对应一类此前测试矩阵未覆盖的维度——
打包完整性、系统代理、Hardened Runtime 权限、剪贴板副作用、以及最关键的
**输入规模与递归深度**。

---

## 5. v0.3.0：从固定流水线到有边界的端侧 Agent

### 5.1 v0.2.6 与 v0.3.0 的核心差异

相对于 `v0.2.6`，v0.3.0 发布基线横跨 40 多个已跟踪文件，并新增了 `agent/`、
`semantic/`、`tools/`、`core/repair.py` 及对应测试文件。精确行数会随发布整理变化，
关键是执行模型变化：

```text
v0.2.6:
InputRouter
  → IntentClassifier
  → SymbolEngine
  → MiniCPM pure chat
  → Operator-Drift Guard
  → Validator/Fixer
  → Renderer

v0.3.0:
NL / OCR candidate / Completion candidate
  → SymbolEngine anchors or candidate intake
  → compile_tex Observation
  → MiniCPM5 Planner
  → TeX Tool
  → Observation
  → MiniCPM5 Planner
  → bounded runtime guard
  → structured final result
```

v0.3.0 不是把所有旧代码丢掉重写。IntentClassifier 仍用于受约束回退，SymbolEngine
仍生成权威算符锚点，Operator-Drift Guard 仍负责 Level 0，Validator、Fixer、
RenderEngine、HistoryStore 与设置系统继续复用。新增层的目标是让旧能力成为可调度
工具，而不是让 Planner 重复实现旧能力。

### 5.2 为什么不是“一次性 LLM 输出”

一次性输出有三类不可观测失败：

- 模型生成了无效 LaTeX，但用户只看到渲染失败；
- 模型丢失关键结构，但语法仍合法；
- 模型做了修复，但无法解释改了什么。

Planner/Tool/Observation 循环把这些失败拆开。例如模型先生成候选，调用
`compile_tex` 得到 brace 或 KaTeX 诊断；再调用 `repair_tex`，由确定性规则得到新候选
和 Semantic Diff；最后调用 `render_math`。每一步都能进入 trace，用户和测试都能
看到决策依据。

### 5.3 为什么 Agent Runtime 不自创协议

MiniCPM5 的原生工具格式使用 XML function block：

```xml
<function name="compile_tex">
  <param name="latex"><![CDATA[\frac{a}{b}]]></param>
</function>
```

某些推理服务会把它解析为 OpenAI `tool_calls`，另一些会把原始 XML 放在 content。
TeXada 的 `MiniCPMToolCallParser` 同时接受两种表示，将其归一化为
`PlannerToolCall`。运行时内部只处理统一对象，不再定义一套 TeXada 专属 JSON Agent
协议。这样既尊重模型原生能力，又避免路由器、UI 和工具层依赖某个服务端字段。

CDATA 很重要。LaTeX 包含大量反斜杠、花括号、换行和可能破坏 XML 的符号，普通
文本节点很容易被错误转义。解析器既接受标准 CDATA，也提供有限的容错回退；但容错
不是纵容任意格式，未知工具和非法参数仍由 ToolRouter 返回显式错误。

### 5.4 运行时状态机

Agent Runtime 的状态不是一个隐式 while loop，而可以写成以下状态机：

```text
READY
  → PREPROCESSED
  → PLANNER_TURN
      ├─ tool_calls → EXECUTING_TOOLS → OBSERVED → PLANNER_TURN
      ├─ final latex → OPERATOR_GUARD
      └─ empty       → FALLBACK
  → FINAL_COMPILE
      ├─ invalid → REPAIR → RECOMPILE
      └─ valid   → RENDER
  → COMPLETED
```

每次 Planner turn 都记录 step、content、tool calls 和 observations。运行时保存
`latest_latex`、`semantic_diff`、token 数、停止原因、工具指纹和连续错误数。停止
原因不是装饰字段，它区分：

- `planner_final`：Planner 主动完成；
- `repeated_tool_call`：相同规范化调用被阻断；
- `tool_error_limit`：连续错误达到上限；
- `max_steps_or_empty_final`：达到步数或没有可用 final；
- `operator_drift_recovered`：Planner 漂移后由受约束路径恢复；
- `operator_drift_unresolved`：最后仍未满足算符锚点。

这些原因将来可以进入质量数据集，帮助判断问题来自模型、工具、prompt 还是输入。

### 5.5 为什么上限是三轮

三轮不是一个神秘的最优数字，而是端侧 1B 模型、桌面交互延迟与容错能力之间的工程
折中。常见路径可以在三轮内完成：

1. parse 或 compile；
2. repair 或 semantic diff；
3. render 或 final。

超过三轮后，小模型更容易重复、扩大转义、遗忘原任务，用户等待时间也可能从几十秒
增长到数分钟。运行时允许配置，但默认三轮，并且 runtime guard 不计入 Planner 自由
循环。换言之，系统可以在 Planner 停止后做必要的确定性收尾，却不允许模型无限自治。

### 5.6 真实 E2E 暴露出的反斜杠增长

真实 Ollama 工具调用测试发现，一个候选可能在多轮中从 `\int` 变成 `\\int`，再变成
`\\\\int`。如果直接比较原始参数，调用指纹每次不同，重复调用熔断无法触发；KaTeX
还可能把双反斜杠解释为换行，导致错误字符串被误认为另一种合法结构。

因此 v0.3.0 在工具调用进入 fingerprint 和执行前做窄范围规范化：

- 非环境公式中，命令前连续反斜杠折叠为一个；
- `\int\int` 规范化为 `\iint`；
- `\int\int\int` 规范化为 `\iiint`；
- 含 `\begin{...}` 的矩阵保留合法 `\\` 行分隔。

这不是通用 LaTeX formatter，也不应不断扩大成正则重写器。它只是修复已在真实模型
路径中复现的传输/生成别名，并由矩阵回归测试保护。

---

## 6. 六个 TeX Tools 的职责设计

### 6.1 `parse_tex`

输入裸 LaTeX，输出 `SemanticDocument`。它不验证业务意图，不修改输入，不渲染。
Observation 包含：

- 原始 latex；
- parser backend；
- schema version；
- Semantic Unit 根节点；
- 非致命 diagnostics。

单一职责使 Parser 可独立做兼容性测试，也允许 Planner 在不触发修复或渲染的情况下
查看结构。

### 6.2 `compile_tex`

`compile_tex` 负责回答“这个候选是否通过当前本地验证契约”。它组合已有
LaTeXValidator 与 Semantic Parser，返回 valid、结构化 diagnostics 和
SemanticDocument。这里的“compile”并不声称执行完整 TeX Live；当前契约包括括号、
环境、命令和可用时的 KaTeX 检查。

命名为 compile 而非 validate，是为了让 Planner 把它理解为候选进入最终输出前的硬
门槛。但文档必须说明它不是完整宏展开器，不能保证任意 LaTeX 宏包都可编译。

### 6.3 `repair_tex`

Planner 不得直接“顺手改一下”坏公式，而应把原始候选交给 `repair_tex`。
`repair_tex` 调用 `DeterministicRepairService`，输出：

- original；
- repaired latex；
- changed；
- valid；
- repair_method；
- diagnostics；
- repair log；
- before/after Semantic Diff；
- 修复后 SemanticDocument。

这个契约要求修复结果必须重新验证。规则输出也不是自动正确的事实，只有通过
validator 且能生成结构 Observation 的候选才能进入下一步。

### 6.4 `semantic_diff`

输入 before 和 after 两个公式，输出结构变化、加权成本、归一化距离、相似度和 reward。
它不判断“after 一定更好”，因为 Diff 只能回答发生了什么，不能在没有任务目标时判断
对错。正确性必须结合 compile 结果、用户指令或训练标签。

对齐超出资源预算时（见 §8.4），Diff 返回 `degraded: true` 的线性近似结果：它
仍然给出顺序对齐和 edit script，但不再保证 O(m·n) 动态规划的全局最优。调用方
（Planner、UI、训练数据管道）必须把 `degraded` 当作一等字段处理，不能把降级
结果当成与完整 DP 同精度的 Observation。

### 6.5 `render_math`

渲染工具将合法候选转为 KaTeX HTML 或纯 LaTeX 高亮，同时返回 copy text 和
SemanticDocument。Render 不承担修复职责；失败时使用可见 fallback，避免 UI 空白。

### 6.6 `export`

导出工具只处理表现形式：bare LaTeX、inline、display 或 Markdown。它不重新生成
公式。这一工具看似简单，却能阻止 Planner 自己添加错误的 `$`、`$$` 或 fence。

### 6.7 ToolRouter 的边界

ToolRouter 维护显式白名单和 JSON schema，未知工具返回错误 Observation，而不是
通过 `getattr` 调用任意方法。参数必须是对象，LaTeX 有最大长度，枚举字段会验证。
工具捕获预期的 TypeError、ValueError 与 RuntimeError，并记录耗时。

v0.3.8 起，工具执行本身也有边界：TeX 工具在 worker 线程上运行（
`asyncio.to_thread`），并带可配置的墙钟超时（`tool_timeout_seconds`，默认 10
秒），不再阻塞事件循环。需要明确的是，超时只终止请求的等待，不能终止正在运行的
worker 线程——线程会继续跑完。因此超时是请求级预算，不是计算级隔离；对高风险
计算，进程隔离（CAS 已采用的父进程 timeout + PID-RSS 限额）仍是更硬的边界。

这个边界同时是安全边界：Planner 不能调用删除文件、执行 shell 或修改设置。TeXada
的 Agent 权限只覆盖数学工具，不因“Agent”二字获得通用电脑控制能力。

---

## 7. KaTeX AST 到 Semantic Unit

### 7.1 为什么选 KaTeX

LaTeX 本质是宏语言，完整解析意味着处理宏展开、作用域、类别码和大量包扩展。TeXada
当前目标是常用数学表达，不应从零写一个 TeX 引擎。仓库已经 vendored KaTeX 资源，
KaTeX 对常用数学语法、矩阵、上下标、分数和根式有成熟 parser，因此适合作为第一层
语法树来源。

但 KaTeX 公开接口主要面向渲染，`__parse` 是内部接口。v0.3.0 的策略是：

- 固定 KaTeX 0.17.0，不使用 `^0.17.0` 浮动版本；
- 将 `__parse` 调用隔离在 `semantic/katex.py`；
- 不从 CDN 下载代码，直接读取仓库 vendored JS；
- wheel 和 PyInstaller sidecar 显式打包这份 JS；
- 升级 KaTeX 时集中运行 AST mapping 测试。

### 7.2 为什么使用进程内 V8

Python 调用 KaTeX 有三种常见方式：

1. 每次启动 Node 子进程；
2. 维护常驻 Node daemon，通过 stdin/stdout 通信；
3. 在 Python 进程中嵌入 V8。

Planner 循环会高频调用 parse、compile、repair 和 diff。每次启动 Node 会产生明显
进程开销；daemon 很稳定，但要设计 framing、重启和日志隔离。v0.3.0 选择当前维护的
`mini-racer`，通过 `py_mini_racer.MiniRacer` 创建可复用 V8 context。

实际实现还处理了一个容易忽略的问题：MiniRacer 在 async 上下文中创建时会绑定当前
event loop，而 pytest 的异步测试可能关闭这个 loop，导致全局 context 报
“Event loop is closed”。因此 V8 在一个短生命周期的普通 worker thread 中创建，
让 mini-racer 启动自己的持久事件循环；之后通过锁安全复用。这个修复来自真实测试，
不是预先想象的抽象复杂性。

v0.3.8 又补了两层生命周期边界。第一层是自愈：V8 context 在深嵌套输入等故障
场景下可能崩溃，现在失败后会自动重建，最多重建 3 次（`MAX_CONTEXT_REBUILDS`），
超过后保持不可用而不是在紧循环里反复重建。第二层是退出：共享 parser 通过
`atexit` 在解释器退出时显式关闭，CLI、脚本与后端进程都能干净退出，不残留后台
V8 线程。这两层与前文的深度上限（`MAX_NESTING_DEPTH=100`，在任何 V8/KaTeX
调用前检查）共同构成纵深防御：前置扫描挡住病态输入，重建处理偶发崩溃，atexit
保证失败路径不留残留。

### 7.3 为什么不能直接 Diff KaTeX JSON

KaTeX AST 是渲染导向树，包含 loc、style、spacing、font、color、sizing、mclass 等
信息。如果直接对原始 JSON 使用 DeepDiff，会出现两个问题：

- 相同数学语义因为位置、空格或样式不同产生大量噪声；
- 通用 diff 输出 `values_changed` 或数组下标，对 1B Planner 和用户都不友好。

因此最值得投入的不是通用 diff 库，而是归一化层。`_KaTeXSemanticMapper` 将 KaTeX
节点映射成领域节点：

- `genfrac` → `fraction`，子角色为 numerator/denominator；
- `sqrt` → `root`，子角色为 index/radicand；
- `supsub` → `script`，或附着到 integral/summation/product；
- `op` → integral、summation、product、limit；
- `array + leftright` → matrix environment、row、cell；
- `ordgroup` → group；
- style、spacing 等表现节点被折叠或忽略；
- 未识别节点保留为 `katex_node`，而不是静默丢弃。

Semantic Unit 只保留 kind、value、role、children、语义 attributes 和可选 source。
source 用于展示，不参与指纹；否则同一结构的不同拼写无法判等。

### 7.4 容错 Parser 的位置

KaTeX 对 `\frac{a}{b` 之类畸形输入会抛出精确错误，但 repair_tex 恰恰需要看到坏
公式的大致结构。因此系统保留一个小型 tolerant fallback parser：

- 正常公式以 KaTeX 为权威；
- KaTeX 失败或自定义宏不支持时，fallback 尽量提取 command、group、script 等；
- KaTeX 原始错误进入 diagnostics；
- `parser_backend` 明确标识 `katex-0.17.0-v8` 或 `tolerant-fallback`。

fallback 不是第二个完整 parser，更不能逐步膨胀为手写 TeX 实现。它只为错误恢复
提供最低结构信息。若未来自定义宏需求扩大，应增加宏预处理或可配置 parser adapter，
而不是继续堆正则。

---

## 8. Semantic Diff 算法设计

### 8.1 算法选择结论

当前采用：

> **规范化 Semantic Unit + 子树哈希剪枝 + 数学角色优先匹配 + 加权有序子树对齐。**

它借鉴树编辑距离思想，但不是直接调用 zss/APTED，也不是对原始 KaTeX JSON 使用
DeepDiff。原因如下：

- zss/APTED 擅长给出最小编辑距离，但默认标签成本不知道 numerator 比 spacing 重要；
- DeepDiff 适合通用对象调试，但原始路径难以表达数学角色；
- TeXada inference observation 既需要数值，也需要人和 Planner 能读的 edit script；
- 规范化后的树已经限制了问题规模，可以使用更简单、可控的动态规划。

最后一句需要 0.3.8 的修正：规范化限制的是**节点种类与噪声**，并没有限制**节点
数量、树深度或对齐矩阵规模**。输入长度上限不能约束递归深度或算法复杂度——模型
生成的 LaTeX 即使语法合法，也可能自然或恶意触发最坏情况。因此“可控”是有条件的：
只有显式设置结构深度与算法规模预算后，这个动态规划才是可控的（见 §8.4）。

### 8.2 第一步：稳定子树指纹

每个 Semantic Unit 以 kind、value、role、排序后的 attributes 和子节点指纹生成
SHA-256。source 和字符位置不参与。若 before 与 after 指纹相同，整棵子树直接跳过。

这一优化不仅提高速度，更重要的是保证表现层差异不会泄漏到编辑脚本。例如：

```text
x + y
x\,+y
```

KaTeX spacing 节点在归一化时被忽略，两棵 Semantic Tree 指纹相同，最终 distance
为 0、similarity 为 1。

### 8.3 第二步：角色优先匹配

分数、根式、积分和脚本的孩子不是普通数组位置。若分子前插入一个 group，不应导致
分子与分母错配。因此算法先匹配双方唯一且同名的 role：

- numerator 对 numerator；
- denominator 对 denominator；
- lower_bound 对 lower_bound；
- upper_bound 对 upper_bound；
- subscript 对 subscript；
- superscript 对 superscript；
- radicand 对 radicand。

角色匹配后，剩余无角色孩子才进入有序对齐。这样 `\frac{a}{b}` 到
`\frac{a}{c}` 会得到类似：

```text
operation: update
path: root[0].denominator[0]
before: b
after: c
```

而不是“第 9 个字符 b 变成 c”。

### 8.4 第三步：有序动态规划

对剩余孩子构建二维 DP 表。每个单元有三种选择：

- match/replace：比较 before child 与 after child；
- remove：删除 before subtree；
- add：增加 after subtree。

相同指纹的 pairing cost 为 0；相同 kind 的 value 变化成本较低；不同 kind 的成本
取替换子树与删加两者中更合理者；双方都有不同 role 时，避免把它们强行配对。回溯
DP 表后生成稳定 edit script。

这个算法是有序的，因为数学表达的 token 顺序通常有意义；同时角色预匹配解决了
最关键的跨位置问题。未来若需要检测交换律等代数等价，不能简单设置
`ignore_order=True`，而应另建代数 canonicalizer。

**资源预算（v0.3.8 起）**：DP 表大小是剩余孩子列表长度的乘积。当
`len(before) × len(after) > 10_000` 时（一条像 `x_1 + x_2 + ... + x_300`
这样的长平铺公式即可超过），继续 O(m·n) 对齐会从“可控”变成“卡死”：实测
n=1200 时约 65 秒，n=2000 时内存耗尽触发 SIGBUS。因此超过预算后算法降级为
线性顺序对齐（`_degraded_align`），并报告 `degraded: true`。代价是精度下降：
降级结果不再保证全局最优 edit script，只能保证是顺序合理的近似。API 通过
`degraded` 字段显式披露这一状态，而不是静默返回一个假装精确的结果。

### 8.5 加权成本

不同节点的语义重要性不同。当前权重大致遵循：

- sequence/group：低权重；
- symbol/number：基础权重；
- command：中等；
- script：较高；
- root、summation、product、limit：高；
- fraction、integral、environment、syntax repair：最高一档；
- numerator、denominator、上下界、上下标等关键角色变化额外加权。

权重不是数学真理，而是产品先验。它表达“丢掉积分”和“把变量 b 改成 c”都应被记录，
但前者对结构完整性的影响通常更大。后续应使用真实纠错数据校准，而不是无限手调。

### 8.6 Distance、Similarity 与 Reward

总成本除以 before/after 最大树权重，得到 `[0,1]` 的 normalized distance；相似度为：

```text
semantic_similarity = 1 - normalized_distance
reward = semantic_similarity
```

将 reward 暂时设为 similarity 的好处是接口直观；但训练时不能直接把它当唯一奖励。
一个语法合法但回答错误的公式，可能与输入参考结构相似。更完整的训练 reward 应组合：

```text
Reward =
  compile_gate
  × operator_anchor_score
  × semantic_similarity
  × task_constraint_score
```

其中 compile_gate 对无效公式可设为 0；operator anchor 确保关键算符不丢；task
constraint 由标注或任务类型提供。Semantic Diff 是奖励的一部分，不是正确性神谕。

### 8.7 为什么“自然语言 vs 输出公式”不能直接做 Level 1

Operator-Drift Guard 可以在预翻译文本中找到 `\iint`，因为它只关心少量锚点。但
自然语言并不是一棵完整参考公式树。“求一个二重积分”与最终
`\iint_D f(x,y)\,dx\,dy` 必然在大量节点上不同。若直接 DeepDiff，所有合理生成都会
被判为变化。

因此 Level 1 只在以下场景启用：

- repair 前后；
- 用户明确编辑一个已有公式；
- OCR 有可用结构参考或人工标注；
- 训练数据有 source/target；
- Planner 明确调用 before/after diff。

对于纯自然语言生成，Level 0 锚点、compile 和任务约束更可靠。这个边界防止系统因为
“有了 AST”就滥用 AST。

---

## 9. 两级 Guard 的组合

### 9.1 Level 0：守“有没有”

Level 0 沿用原始 Operator-Drift Guard。它检测关键算符存在性和积分等级，复杂度近似
字符串扫描。优点：

- 极快；
- 可在完整参考结构不存在时运行；
- 对 1B 最常见的算符丢失非常有效；
- Observation 容易转化为硬约束。

v0.3.0 将它从 InputRouter 私有方法提取成共享类，但保留兼容 wrapper，使旧测试和旧
路由不被破坏。

### 9.2 Level 1：守“结构变了什么”

Level 1 使用 Semantic Diff。它能发现：

- 分母从 b 变成 c；
- 下标变成上标；
- 根指数丢失；
- 积分上下界变化；
- 普通 symbol 被替换成 fraction；
- matrix row/cell 增删；
- 畸形语法经 repair 后恢复。

它成本高于 Level 0，但仍在本地、无模型完成。

### 9.3 失败反馈与受约束回退

Planner 输出漂移时，运行时生成 `operator_drift_guard` Observation，列出
`required_operators` 和 retry instruction，回灌到有界循环。如果 Planner 重复调用
或三轮后仍漂移，系统使用历史上已经验证有效的 intent-specific
`generate_latex(..., force_operators=...)` 做最后一次受约束尝试。只有锚点全部存在时
才采纳；否则保留第一次候选并标记 unresolved。

真实本地 E2E 中，“二重积分 f(x,y) 在区域 D 上”最终恢复为：

```latex
\iint_D f(x,y)\,dx\,dy
```

停止原因为 `operator_drift_recovered`，之后仍执行 compile 和 render。这说明新 Agent
没有抛弃旧守卫，而是把它升级成可观察的 runtime policy。

---

## 10. 双模型边界：为什么产品不再包含 TeX2TeX

### 10.1 为什么修复仍不应由 Planner 完成

Planner 的训练目标是通用指令理解和工具选择，不是每一种 TeX 错误的最优序列修复。
让它直接修复会造成：

- 修复行为散落在 prompt，无法独立评估；
- 模型升级后修复能力不可控；
- 很难用确定性单元测试覆盖所有 prompt 分支；
- Planner 可能“修复”语法时改掉数学含义。

因此 `repair_tex` 的任务被刻意收窄：

```text
输入：畸形或可疑 LaTeX + diagnostics
动作：应用有界、可解释的语法规则并重新校验
输出：修复后的 LaTeX + repair_method + diagnostics + Semantic Diff
```

它只负责括号、环境、已知命令等语法层问题，不负责猜测缺失的数学含义。

### 10.2 为什么删除“可选 checkpoint”适配器

早期 v0.3.0 草案曾加入一个没有实际 checkpoint 的模型适配器：缺省走确定性
baseline，配置路径后才加载 Transformers Seq2Seq。这个接口虽然技术上可运行，却
在产品语义上制造了三个问题：

- 用户会误以为当前产品已经使用第三个修复模型；
- 配置、打包和错误路径为一个不存在的模型能力付出复杂度；
- “Planner + Vision + Repair Model”破坏了清晰的双模型故事。

最终决策是彻底删除 `tex2tex/` 包、checkpoint 配置、Transformers backend 和相关
环境变量。TeXada 当前只有两个推理入口：

```text
MiniCPM5-1B     → 文本生成、Planner、Tool Calling、状态控制
MiniCPM-V 4.6   → 图片理解、公式 OCR
```

其余能力全部是软件工具，不再使用“模型边界”“backend baseline”之类容易误解的
命名。

### 10.3 确定性修复的验证与失败边界

`DeterministicRepairService` 先取得 validator diagnostics，再调用已有
`LaTeXFixer`，之后重新校验候选并计算 Semantic Diff。返回字段
`repair_method=deterministic-rules`，让 trace 明确说明没有发生模型推理。

如果规则无法修复，工具会返回 `valid=false` 和 diagnostics，运行时不会虚构一个
成功结果。涉及分子内容丢失、积分域误识别、变量替换等数学语义错误时，应让
MiniCPM5 基于新的 Observation 重新规划，或交给用户确认；不能把一个语法 Fixer
包装成“智能修复模型”。

### 10.4 双模型并不等于两个自治 Agent

MiniCPM-V 4.6 不拥有独立规划循环。它只生成 OCR 候选；运行时先把候选交给
`compile_tex`，再把真实 Observation 送入唯一的 MiniCPM5-1B Planner。补全也采用
同一边界：规则或 MiniCPM5 生成候选，随后进入共享 Planner。这样可以避免视觉模型
成为第二个自治 Agent，也让失败定位保持清晰：图片识别问题归 OCR，工具选择问题归
Planner，语法问题归 Validator/Fixer，结构差异归 Semantic Diff。

---

## 11. API、桌面与兼容性设计

### 11.1 为什么新增 `/api/agent` 而不是直接改坏 `/api/convert`

`/api/convert` 已经被旧前端、脚本、E2E 和用户流程使用。若直接改变它的响应结构和
随机行为，v0.2.6 以前的客户端会失效。v0.3.0 新增 `/api/agent`，返回：

- 传统 LaTeXResponse 字段；
- `semantic_document`；
- `semantic_diff`；
- `agent_trace`；
- `stop_reason`。

桌面 NL tab 切换到新路径；旧 convert 保留为 compatibility route。OCR 与补全端点
也复用 `AgentResponse`，因此三个产品入口都返回 `semantic_document`、
`semantic_diff`、`agent_trace` 与 `stop_reason`。这个策略仍保留 pure-chat 与 agent
路径的 A/B 基线，同时统一产品面的可观测性。

### 11.2 Trace 为什么要进入 UI

如果 trace 只存在后端日志，它只能帮助开发者。结构化编辑器需要让用户知道：

- 当前是 Planner 生成还是确定性规则修复；
- 哪个工具失败；
- 是否触发 operator drift；
- 最终是否通过 runtime guard；
- 为什么结果与输入不同。

因此 UI 增加可折叠执行轨迹和 `MiniCPM5 Agent` source badge。默认折叠避免普通用户
被内部细节淹没，展开后又能支持人肉 E2E、错误报告和研究分析。

### 11.3 浏览器开发与 Tauri 产品面的关系

静态浏览器 UI 是开发入口，Tauri 是发布入口。二者共享前端资源和 FastAPI，但能力
不同：

- 浏览器模式用 clipboard fallback；
- Tauri 可调用原生光标插入、全局快捷键、托盘和窗口拖动；
- Tauri 能管理 bundled backend sidecar；
- 浏览器模式便于快速人肉 E2E，不应被误认为最终安装包验证的全部。

发布门禁仍需 Cargo check、sidecar 打包、签名和平台安装测试。当前本地 E2E 证明
Agent HTTP 与 UI 路径可用，不等于已经发布一个新的 DMG/NSIS。

### 11.4 CORS 与本地安全

FastAPI 只允许配置中的本地开发和 Tauri origin。浏览器对 `/api/agent` 的预检需要
通过，其他 origin 被拒绝。Agent ToolRouter 只暴露数学工具，API Key 不进入备份，
这三层共同限制了本地服务的攻击面。

---

## 12. 测试策略：每一种 Diff 对应一种证据

### 12.1 单元测试

无模型测试覆盖：

- MiniCPM XML 与 OpenAI tool call 归一化；
- fraction、root、integral、matrix Semantic mapping；
- spacing 等价；
- denominator 和 script role Diff；
- 工具 schema 与未知工具拒绝；
- repair_tex backend 标识与验证；
- Planner 多步调用；
- 三轮上限、重复调用、连续错误熔断；
- operator drift、反斜杠规范化和矩阵行分隔保护；
- API trace 与 semantic document。

这些测试必须快、稳定，不依赖 Ollama。它们是每次改动的第一层反馈。

### 12.2 集成测试

FastAPI TestClient 验证路由存在、响应结构、历史写入、设置重建 runtime、CORS、
上传限制与备份行为。工具测试使用真实 Validator、Parser、Renderer，但模型被 fake
planner 替代。这样可以测试状态机而不引入采样随机性。

### 12.3 真实模型 E2E

设置 `TEXADA_RUN_E2E=1` 后，测试连接真实本地服务。当前关键用例包括：

- status 确认 MiniCPM 和视觉模型 ready；
- `/api/agent` 处理二重积分并保留 `\iint`；
- Semantic backend 为固定 KaTeX V8；
- trace 以 runtime guard 结束；
- 旧 convert 仍返回非空、有效、可渲染 LaTeX；
- shorthand 创建、查询、转换与删除闭环；
- valid/invalid LaTeX 校验；
- OCR 上传路径。

真实模型测试不应对所有随机输出做逐字符断言。旧 generic pure-chat 路径只检查协议和
可用性；关键数学语义由具有 Operator Guard 的主 Agent 用例断言。否则一次采样变化
会让 CI 把模型基准误判成代码回归。

### 12.4 构建与依赖门禁

当前 CI（`.github/workflows/audit.yml` 与 `release-desktop.yml`）验证包括：

- Ruff；
- pytest（含版本同步与前端契约测试）；
- `pip-audit --strict`（经 `uv export` 审计真实依赖树，而非 `uvx` 临时环境）；
- npm audit；
- JavaScript syntax check（`node --check`）；
- Cargo check（macOS 与 Windows 双矩阵）；
- 桌面发布流水线：PyInstaller sidecar 构建、macOS 签名/公证与安装包
  smoke test、Windows NSIS 安装包。

这些证据分别覆盖源代码、依赖供应链、Python 包、前端脚本和桌面壳，不能用“单元测试
全绿”替代。

### 12.5 当前已验证结果

v0.3.0 发布基线在本地发布前验证中的结果为：

- 189 个离线测试通过；
- 8 个 live E2E 在默认离线套件中按设计跳过；
- 32 个真实本地 API 黑盒 case 与 NL/OCR/补全三个 UI 代表用例通过；
- Ruff 与 `git diff --check` 通过；
- wheel 必须继续包含 `texada/semantic/vendor/katex.min.js`；
- Cargo check、依赖审计、sidecar 打包和多平台安装仍是正式 tag 前的发布门禁。

仓库仍有一个来自第三方 Starlette TestClient 的弃用警告，它不影响当前功能，但后续
升级 FastAPI/Starlette/httpx 时应处理，避免警告长期变成兼容故障。

v0.3.2 又增加了一层“能力先验收、产品后接入”的 CAS 门禁，但没有改变桌面产品
行为：

- `src/texada/cas/` 只作为可选、未注册的能力骨架；
- 生产方向只允许 `Semantic Unit → 白名单 SymPy`，不把 raw LaTeX parser 当权威；
- 结果拆分为 status、basis、evidence grade、assumptions、witness、seed 与版本；
- `.equals() == False` 永远只是 observation，有限精确反例才可支持 different；
- 常驻 worker 每任务重置 seed，并由父进程执行 timeout 与 PID-RSS 限额；
- `eval/cas_capabilities.yaml` 是机器可读真相源，Markdown 由它生成；
- 发布候选为 281 项离线测试通过、8 项 live E2E 按设计跳过，CAS 定向 35 项连续
  五轮通过。

这不代表 v0.3.2 已向用户提供 algebra checker。公开工具仍为六个，Agent、API 与 UI
均未注册 CAS；它验证的是“目前能够安全支持或拒绝什么”。

v0.3.8 的验证结果（详见 CHANGELOG）：

- 新增 19 项安全回归测试（`tests/test_safety_guards.py`），全部离线、无模型；
- 三条 DoS 类路径均已实测复现并验证被边界挡住：3151 字符深嵌套 `\frac` 链、
  n=2000 的 `semantic_diff`、无上限的工具调用；
- 工具墙钟超时、V8 自愈与 `atexit` 释放、`SymbolEngine` 单遍改写均有对应
  回归覆盖。

### 12.6 复杂度与安全回归测试（v0.3.8 起）

0.3.8 的 19 个测试不是普通的新增 case，而是一种新的测试范式：**复杂度回归测试**。
普通单元测试断言“给定合法输入，输出正确”；复杂度回归测试断言“给定病态输入，
系统在预算内降级、失败或拒绝，而不是崩溃、挂死或耗尽内存”。它检查的是资源边界
本身，而不是业务正确性：

- 深嵌套输入触发深度上限（拒绝）而不是 `RecursionError` 击穿进程；
- 超大 Diff 触发线性降级并返回 `degraded: true`，而不是 65 秒等待或 SIGBUS；
- 工具调用在墙钟超时内返回错误 Observation，而不是无限阻塞事件循环；
- 同一输入在 V8 重建后仍可继续服务，进程退出无残留。

这类测试与功能测试正交，应作为独立类别持续扩充：每新增一个“可能被模型输出
放大”的确定性算法（parser、serializer、diff、修复规则、渲染），都应配套一个
复杂度回归 case，而不只配套正确性 case。这也是 §2.6 第六设计哲学的测试落地。

---

## 13. 架构决策记录

### ADR-001：不把 TeXada 定义成通用 Agent 框架

**决定**：只建设数学工具与 MiniCPM5 Planner Runtime。

**原因**：通用浏览器、shell、文件和网络工具会扩大权限与测试面，却不提高公式修复
质量。TeXada 的壁垒是 Semantic Unit、双模型协作和端侧编辑体验。

**后果**：其他项目不能直接拿 TeXada 当通用 Agent SDK；这是有意限制。

### ADR-002：保留 Operator-Drift Guard

**决定**：Semantic Diff 不替代字符串级算符守卫。

**原因**：自然语言没有完整参考 AST，而算符锚点可以从 SymbolEngine 可靠提取。
Level 0 成本低、召回关键，Level 1 粒度细，二者互补。

### ADR-003：不在第一版引入 DeepDiff

**决定**：先归一化领域树，再输出领域 edit script。

**原因**：原始 KaTeX JSON 的 loc、style、spacing 噪声会制造无意义差异；通用路径
不适合作为 Planner Observation。真正值得长期维护的是 normalization。

**后果**：需要自己维护有限的对齐算法，但代码规模和测试面可控。

### ADR-004：不直接依赖 zss/APTED

**决定**：实现 role-aware ordered child DP，并保留未来替换可能。

**原因**：当前树小、角色明确，需要 edit script 多于一个抽象最小距离。引入旧依赖
会增加打包与维护成本。

**后果**：当前不是完整的任意树移动算法，也不处理代数交换等价。

### ADR-005：固定 KaTeX 版本

**决定**：使用精确 0.17.0，并隔离内部 `__parse`。

**原因**：内部 AST 不是稳定公开契约；浮动 semver 会让 mapper 在无代码变化时破坏。

**后果**：升级需人工检查 AST fixture、wheel 和 sidecar。

### ADR-006：产品只保留两个模型角色

**决定**：删除 TeX2TeX、可选 checkpoint 与 Transformers repair backend；
`repair_tex` 只暴露确定性规则修复，并返回 `repair_method`。

**原因**：当前产品实际只有 MiniCPM5-1B 与 MiniCPM-V 4.6。保留空模型接口会让
文档、配置、打包和用户认知同时失真。

**后果**：当前 repair 上限明确受规则 Fixer 限制，但模型清单、运行时和产品承诺
完全一致。

### ADR-007：新旧 API 并存

**决定**：UI 主路径迁移到 `/api/agent`，保留 `/api/convert`。

**原因**：保护既有客户端和数据流程，同时允许新响应增加 trace。

**后果**：短期维护两条 NL 路径；未来需用遥测和版本策略决定何时废弃旧路径。

### ADR-008：运行时安全优先于 Planner 自治

**决定**：三轮上限、重复调用阻断、两次工具错误熔断、强制最终 compile/render。

**原因**：端侧 1B 的循环与格式错误是可预期风险。

**后果**：少数确实需要四轮以上的复杂任务会提前停止，但结果仍可恢复和观察。

### ADR-009：CAS 先作为未注册能力门

**决定**：v0.3.2 允许仓库提前拥有可选 CAS adapter、worker、policy 与评测矩阵，
但在错误 verified 未稳定为零、能力边界未审计前，不把 `algebra_check` 注册进
`TeXToolset`、Agent、API 或 UI。

**原因**：raw `parse_latex` 会静默漂移，`.equals()` 的否定结果既不完备又受随机
采样影响，非有限对象和 assumptions 还会改变结论。先建立白名单与可复现证据契约，
比先暴露一个看似通用的验证按钮更安全。

**后果**：默认 sidecar 与桌面安装包不引入 SymPy/psutil；源码贡献者可通过
`cas`/`cas-eval` 可选依赖运行门禁。v0.7 路线仍代表真正的产品接入，而不是本次
基础设施提交。

### ADR-010：所有模型可达工具必须资源有界

**决定**：Parser、Semantic Serializer、Semantic Diff 与 Tool execution 分别
设置结构深度、算法规模与 wall-clock 预算；超限时返回显式降级结果，不继续追求
精确计算。具体为：V8/KaTeX 调用前检查嵌套深度上限（`MAX_NESTING_DEPTH=100`）；
Diff 在 `len(before) × len(after) > 10_000` 时切换线性对齐并返回
`degraded: true`；工具在 worker 线程执行并受 `tool_timeout_seconds`（默认 10
秒）墙钟超时约束。

**原因**：输入长度上限不能约束递归深度或算法复杂度。模型生成的 LaTeX 即使语法
合法，也可能自然或恶意触发最坏情况——3151 字符的合法 `\frac` 链曾使进程崩溃
或挂死，2000 节点的 Diff 曾触发 SIGBUS。确定性只代表结果可重复，不代表计算
有界、可终止。威胁模型必须同时覆盖“Agent 失控”与“确定性工具失控”。

**后果**：超大 Semantic Diff 采用线性近似并返回 `degraded=true`，精度显式
下降而非静默失真；深度超限返回受控的 Semantic Document 或错误 Observation；
线程超时只终止请求等待，不能终止底层线程，因此高风险计算未来仍应考虑进程
隔离（与 CAS 的父进程 timeout + PID-RSS 限额对齐）。每个新的确定性算法都应
配套复杂度回归测试（§12.6）。

---

## 14. 未来版本的迭代 Diff 思路

以下是设计建议，不是已完成事实。

### 14.1 v0.3.0：Agent 发布基线验收

发布基线的验收目标：

- 正式提交当前 Agent Runtime 与工具层；
- 为 Semantic schema 定版本兼容规则；
- 给 KaTeX mapping 增加 fixture corpus；
- UI 提供更清晰的 tool/observation 摘要；
- 统计 stop_reason 与工具错误；
- 完成 macOS/Windows 真实 sidecar 打包测试；
- 为旧 `/api/convert` 标记迁移计划，但不立即删除。

与 v0.2.6 的产品 Diff 是“结果型工具”变成“过程可观察工具”。验收不只看公式是否
出现，还要看状态机是否按预期停止。

### 14.2 v0.4：确定性修复与质量数据闭环

建议新增：

- 合成错误生成器：括号缺失、环境错配、命令拼写、上下标漂移、反斜杠增长；
- source/error/target 三元组；
- 按 Semantic Unit 分类的错误标签；
- 每条 Fixer 规则的命中率、误修率和回归样例；
- exact match、compile rate、semantic similarity、operator retention 指标；
- 人工确认后可选择保存匿名本地质量样本。

这一版的核心 Diff 是从“有一组修复规则”变成“有可重复评估的修复系统”。若未来
确实需要研究独立修复模型，也应在另一个项目中用这些数据验证价值，而不是把尚未
存在的 checkpoint 预埋回 TeXada 产品。

### 14.3 v0.5：结构化编辑操作

建议让 UI 不只提交自然语言，而能生成明确 operation：

```json
{
  "operation": "replace_denominator",
  "path": "root[0].denominator",
  "value": "x+1"
}
```

这时 Semantic Unit 真正成为编辑模型，而非只用于观察。可支持：

- 点击分子/分母局部编辑；
- 移动积分上下界；
- 上下标互换；
- matrix cell 定位；
- undo/redo 以 Semantic Change 为单位；
- 用户确认某一结构修复而不接受其他修改。

与当前版本的 Diff 是从“字符串结果 + 结构解释”变成“结构操作 + 字符串序列化”。

### 14.4 v0.6：宏、方言与多 Parser 策略

KaTeX 不能覆盖所有 TeX。建议建立：

- macro registry；
- 用户自定义宏展开白名单；
- parser capability 字段；
- KaTeX、LaTeXML 或其他 adapter 的明确选择策略；
- unsupported 节点保真 round-trip；
- 宏展开前后 Semantic Diff。

不要把所有宏塞进 tolerant regex parser。扩展应通过 adapter 和 capability 完成。

### 14.5 v0.7：语义等价与 CAS 辅助

当前 spacing 等价已支持，但 `x+y` 与 `y+x`、`\frac{2x}{2}` 与 `x` 仍会被判为
结构不同。v0.3.2 已先建立未注册的白名单 adapter、隔离 worker 与能力矩阵；
这里的 v0.7 指把经过扩展验证的能力正式接入产品。若产品需要“数学等价”，应继续：

- 扩充并版本化 Semantic Tree → 有限 SymPy expression 的白名单；
- 对每一类代数 canonicalization 建立可审计证据等级；
- 保留表示层 Diff 与代数等价两个维度；
- 不支持的表达式明确返回 unknown。

结构相同、表示相同、代数等价是三种概念，不能压成一个 boolean。

### 14.6 v0.8：Planner 训练与工具调用数据

当真实 trace 足够多后，可构建：

- user → tool call；
- observation → next tool；
- error observation → recovery；
- should-stop；
- duplicate-call negative examples；
- XML/CDATA 格式样本。

训练目标应是让 MiniCPM5-1B 稳定选择工具和停止，而不是让它兼任公式修复网络。
视觉 OCR 数据与 Planner trace 也必须分开，否则两个模型角色会再次模糊。

### 14.7 v1.0：结构化数学编辑器的稳定契约

达到 1.0 前建议满足：

- Semantic schema 有兼容承诺；
- MiniCPM5-1B 与 MiniCPM-V 4.6 的模型边界、版本和部署方式稳定；
- 确定性 repair 有公开规则覆盖率与回归集；
- Agent Runtime 在目标设备上有延迟预算；
- macOS/Windows 安装、升级、备份恢复稳定；
- before/after 编辑可撤销；
- 关键公式类别有人工 E2E；
- 旧 API 有明确去留；
- 本地数据、模型和网络行为均可解释。

1.0 不应由功能数量决定，而应由契约稳定性决定。

---

## 15. 评估指标与观测体系

### 15.1 不只看 Exact Match

同一公式可能有多种 LaTeX：

- 空格不同；
- `\dfrac` 与 `\frac`；
- `\left(` 与普通 `(`；
- matrix delimiter 写法不同；
- 宏展开前后不同。

因此建议至少同时记录：

| 指标 | 回答的问题 |
|------|------------|
| Exact Match | 字符串是否完全一致 |
| Compile Rate | 是否通过本地语法契约 |
| Operator Retention | 关键算符是否保留 |
| Semantic Similarity | 结构变化有多大 |
| Task Constraint Pass | 是否满足用户明确要求 |
| Render Success | 是否可展示 |
| Human Accept | 用户是否接受 |
| Latency | 冷启动、warm、每工具耗时 |
| Planner Steps | 是否在预算内停止 |

### 15.2 结构级错误分类

建议将错误分类为：

- syntax：括号、环境、非法命令；
- operator：积分/求和/极限丢失或降级；
- argument：分子、分母、根式参数错误；
- script：上下标角色或内容错误；
- bound：上下界错误；
- environment：矩阵维度、行列错误；
- presentation：空格、样式、delimiter；
- protocol：XML、JSON、转义错误；
- planning：工具选择、重复调用、未停止；
- rendering：CLI、字体、资源问题。

这比一个总准确率更能指导版本 Diff。若 syntax 已很低而 planning 很高，就不应继续
堆 Fixer 规则；若 argument 错误集中出现，应先区分来自 OCR 还是文本生成，再分别
改进 MiniCPM-V 4.6 的识别提示或 MiniCPM5-1B 的规划反馈。

### 15.3 本地隐私下的质量反馈

默认不上传公式。质量数据可先保存在本地：

- trace；
- stop reason；
- tool duration；
- 用户是否复制/插入；
- 用户是否立即修改；
- 修改后的 Semantic Diff。

只有用户明确选择导出或贡献数据时，才生成脱敏包。备份与训练数据导出必须分开，
API Key 和私人历史默认不进入研究数据。

---

## 16. 总结：各版本真正累积下来的资产

回看所有版本，TeXada 的演化不是不断增加模型能力，而是不断把不可靠的隐式行为变成
可靠的显式契约：

- 初始原型证明“自然语言转 LaTeX”有价值；
- v2/M0 把单文件原型拆成可测试模块；
- MiniCPM/Ollama 迁移建立端侧与统一 endpoint；
- Operator-Drift Guard 首次处理“语法正确但答错题”；
- v0.1.0 建立唯一桌面发布面与 sidecar；
- v0.2.0 让历史可复用；
- v0.2.1 让渲染离线可用；
- v0.2.2 让确定性 Preset 不再绕模型；
- v0.2.3 稳定视觉与交互层级；
- v0.2.4 区分恢复结果与复用输入；
- v0.2.5 解决连续使用和多平台壳稳定性；
- v0.2.6 建立本地数据迁移与备份契约；
- v0.3.0 真正加入 Planner、Tool、Observation、Semantic Unit 和双模型边界；
- v0.3.1～v0.3.2 沉淀零模型补全与 CAS 能力门；
- v0.3.3～v0.3.8 收敛发布可靠性、打包完整性与安全边界；其中 v0.3.8 首次为所有
  模型可达工具建立显式的时间、空间与结构预算（ADR-010）。

因此，TeXada 的核心竞争力不应只被描述为“接入了 MiniCPM5”或“能生成 LaTeX”。
字符串生成很容易被复制，长期壁垒来自三件事：

1. **结构数据**：把真实公式错误表达为可学习的 Semantic Unit 与 edit；
2. **专业工具**：Parser、Validator、Fixer、Diff、Render 在端侧可靠协作；
3. **产品闭环**：从输入、观察、确认、编辑、撤销到备份，用户始终掌握结果。

最终目标不是让 Planner 显得更自治，而是让用户在面对复杂数学表达时更少担心：
“它到底改了什么、为什么改、能不能恢复”。当这些问题都有结构化答案时，TeXada 才
真正从 LaTeX 转换器成长为结构化数学编辑器。
