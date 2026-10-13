# MiniCPM-V 4.7 本次验收记录

日期：2026-10-13（Asia/Shanghai）。基础提交：`5c9c13e`。
主模型与视觉模型均为 `MiniCPM-V-4.7-1B`；真实推理由 ModelBest API 提供。
适配与确定性工具在 Apple A18 Pro / 8GB 的本机运行。

## 结果

| 验证 | 结果 | 可支持的结论 |
|---|---|---|
| Python 全套回归 | 519 passed / 8 skipped | 现有状态、工具、协议与新 profile 的回归检查通过 |
| Ruff / JS / shell / diff | 通过 | 静态检查通过 |
| `/models` / 文本 / 图像 / 原生工具调用 | 真实 API 200 | 请求协议、同名模型与标准 `tool_calls` 可用 |
| NL 原初始规划方式，前 20 条 | 锚点 3/19，语法/渲染/提交 7/20 | 直接让 1B 模型规划全工具表不适合这批任务 |
| 同输入、窄提示候选生成 | 锚点 14/19，语法 20/20 | 候选生成能改善初始公式 |
| 同输入、候选优先完整 Runtime | 锚点 11/19，语法/渲染/提交 17/20 | 最终流程改善，仍存在质量与 provider 限制 |
| 候选优先耗时 | p50 6.886s / p95 11.196s | 包含每次请求最少 3.2s 的评测限速，不是裸模型速度 |
| 最终 ASGI API smoke | NL / completion / raw OCR 均有 200、valid、committed 样本 | 本机 FastAPI 与真实云推理联通 |

8 个跳过是要求另启 TeXada 服务并显式设置 `TEXADA_RUN_E2E=1` 的外部 HTTP E2E。
ASGI smoke 不代表已构建、安装或测试 Tauri 桌面包。

NL 实测使用既有黄金集的**前 20 条**。19 条可机器检查，一条是描述性锚点。
这是配对开发 smoke，不能称为完整 100 条验收，也不能代表全部数学任务。

后续增加的[严格完整表达结构评测](strict-structure-eval.md)保留原 containment 指标，
只有显式提供完整参考时才检查，分别报告 `MATCH / DIFFERENT / UNSUPPORTED / NOT_CHECKED`
及覆盖范围。它没有追溯重算本页真实 API 结果；初始参考与对抗 pair 是 agent-reviewed
synthetic author references，不能当作已完成的独立人工复核。
现有子序列锚点 matcher 检查包含关系，可能产生假阳性或假阴性，不能称为完整结构正确率。
例如完整 `cases` 输出可能被不完整的 `\begin{cases}` 锚点判为未命中。

原初始 Planner 对照曾完成 32 条，随后转向候选优先实验；报告配对比较只使用双方
相同的前 20 条。并行的早期探针触发 RPM 限流，原始失败记录保留，但不进入质量比较。
限速后的两个配对阶段没有 429。

最终 NL 的三个错误是 provider `400 / content_policy_violation`，不是数学错误评分。
完整 Runtime 一次旧二值化 OCR smoke 也遭该 provider 拒绝；随后独立 raw OCR
二次方程样本通过。适配器现在立即返回明确的 provider 策略拒绝，不通过移除 tools 重试。
保持拒绝记录，不能把成功样本概括成服务可用率 100%。

## OCR 配对消融

12 张固定生成的印刷公式，分别走 raw、960px 轻缩放、旧二值化/2x 放大，共 36 次真实
视觉推理，均取得回答。原图有哈希与公式真值，不包含手写、照片噪声、矩阵或整页布局。

| 模式 | 双向锚点一致诊断 | 观察 |
|---|---:|---|
| raw | 10/12 | 保留尺寸与颜色，选为新 profile 路径 |
| soft | 9/12 | 一个标量被加粗，未作为默认 |
| binary | 8/12 | 根指数 n 丢失；嵌套分式多出项和括号 |

双向锚点仍是诊断指标，不能证明视觉忠实度；例如微分符号的等价空白写法也可能不一致。
最重要的失败是：真实图像有 `\iint`，模型在三种模式下都输出 `\int`。
这种输出可以通过语法检查，原图对照与人工审阅不可省略。
没有据此声称手写识别质量改善。

## 本机 Q4 与发布边界

官方 1B Q4_K_M 与 projector 已发布，链接和固定 HF revision/SHA256 见
[适配说明](minicpm-v47.md)。本机 `llama-server b10150 / dee2a846b` 是 4.7
支持提交 `69f201a` 的祖先，需升级。此次没有下载权重、验证本机哈希、运行 Q4，
也没有测量 Q4 内存、速度或与 API 的精度差异。

远端 main 与 PR #4 的 HEAD 已只读核查；本次从 main 独立适配。
没有 push、PR、远端 CI、merge 或安装包发布。README 与 ADR 已包含新的官方 HF 链接。
