# Mac mini M4 / 16GB：beta.3 本机实测（2026-10-15）

## 结论与证据边界

本机的内置 llama-server 路线可运行；Ollama 0.40.3 与当时最新的 0.40.4 均无法加载本次官方 4.7 1B 视觉投影文件。推荐本机先用内置路线，不把模型已下载或状态 ready 当作推理验收。

[机器可读摘要与加载失败记录](m4-beta3-validation-summary.json)保存硬件、版本、输入/参考/权重 SHA256、统计及脱敏失败响应。测试使用 beta.3 正式 DMG 的隔离副本和打包后端，未替换现有安装，也未修改原配置。完整逐题 trace、fingerprint、原图、运行日志及报告另外交付给本机用户，没有在仓库内发布完整原始包；此处摘要不等于完整公开复现数据集。

## 环境与过程

- Mac mini Mac16,10，Apple M4 10核、16GB，macOS 26.6.2。
- 同一官方 MiniCPM-V 4.7 1B Q4_K_M 与 F16 projector。模型字节与已冻结 beta 权重 hash 一致。
- temperature=0.1、server seed=47、8192 context、candidate-first=true、full Planner、OCR=binary。这是本次明确设置的测试 profile，不代表所有默认配置。
- beta.3 桌面程序及打包后端启动、原生 NL 输入渲染、原生图片选择及后台 OCR 通过。原生窗口之后无法持续捕获，最终审阅/历史/设置交互用同版本前端在后台浏览器中连接正式打包后端验证，不冒称完整原生布局验收。

## 结果

| 项目 | 观察结果 | 限制 |
|---|---|---|
| 100题 NL / Planner | 100 HTTP成功、99语法通过、100返回渲染、98提交；201次provider调用 | 各字段独立，不是数学正确率 |
| 严格结构 | 49 MATCH、35 DIFFERENT、16 UNSUPPORTED | MATCH不是证明，DIFFERENT不是数学反证 |
| 暖服务端到端延迟 | 中位1.062秒，P95 2.053秒 | 含4条零模型路径，可能受prompt/KV cache影响，不是冷启动或解码吞吐 |
| 新启 beta.3 内置运行时 | 启动7.063秒、首次文本2.541秒、OCR 3.495秒、停止0.178秒 | 另启独立端口；未停止原服务 |
| 补全 | 6条确定性placeholder路径成功；2条模型回退烟测输出被拒交 | 不是补全数学质量验收 |
| OCR | 8张合成印刷公式均进入待审阅；结构7 MATCH、1 DIFFERENT | 没有手写或真实页面验收 |
| 审阅交接 | 错绑定409，正确绑定自动拒绝/采用200；待审阅禁用复制，测试采用后启用 | 全部是测试自动化，不是独立人工审阅 |
| OpenAI-compatible | 文本/OCR真实分路和独立测试Key检查通过 | OCR入口转发至同一模型运行时，不是两个模型A/B或外部云测 |
| 输入错误 | 空输入/非法后端/非法超时422；损坏PNG为500 | 解码ValueError尚未受控处理，需修复 |
| 资源 | 采样进程RSS合计峰值约2.55GiB | 不含完整Metal/统一内存归属；有其他并行应用和既有swap，不能归因或推广 |

## Ollama 复现

按 README 拉取官方 `openbmb/minicpm-v4.7:1b` 时，本机网络把下载域名解析为非公网地址，Ollama 拒绝跳转；没有关闭这项保护。为区分网络问题与加载问题，使用已核实 hash 的官方文件本地导入：

```text
FROM /path/to/MiniCPM-V-4_7-1B-Q4_K_M.gguf
FROM /path/to/mmproj-model-f16.gguf
PARAMETER num_ctx 8192
PARAMETER temperature 0.1
```

```sh
ollama create minicpm-v4.7-1b -f Modelfile
ollama run minicpm-v4.7-1b "Reply only: OK"
```

本机0.40.3导入成功，但实际文本与图片推理均500。随后下载并校验官方0.40.4，在独立端口运行同一模型文件，两类请求同样500；加载日志明确为：

```text
load_hparams: unknown projector type: minicpmv4_7
Failed to load CLIP model
```

TeXada 在这些请求前显示 ready；它反映服务和模型条目存在，未证明该引擎能加载 projector。此结论限定于这里的版本、模型字节和本机测试条件，不推断所有未来 Ollama 版本均不可用。[官方部署指南](https://opensqz.github.io/MiniCPM-V-CookBook/site/en/v4.7/deployment/ollama.html)亦提醒引擎必须支持新的格式。

## 数学语义风险

100条新请求的最终公式与历史 beta 运行逐字节一致，提交状态也一致。仅对完全匹配的候选复用原有 Codex 判定后，24条历史数学错误公式再次提交成功。这不是新的独立判定，也不证明本版数学准确率。原有严格结构评测和人工复核限制继续成立。

本次没有更换模型、修改提交门禁或执行独立人工复核。优先把 Ollama 的加载阻塞与就绪检查边界讲清楚，另行修复损坏图片的受控错误响应；数学误提交继续按逐题证据独立处理。
