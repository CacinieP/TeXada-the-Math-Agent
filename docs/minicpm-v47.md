# MiniCPM-V 4.7 单模型适配

本次从 `main@5c9c13e` 适配 `MiniCPM-V-4.7-1B`，通过 ModelBest API 在本机开发。
OCR 和 Planner 保留两个职责，使用同一个 checkpoint、endpoint 和 API key。
确定性 TeX 工具继续负责解析、语法检查、修复、Diff、渲染和导出。
NL 路径先用窄提示生成公式候选，再进入工具审阅；避免让 1B 模型直接把中文描述
交给 TeX 解析器。profile 自动启用 `TEXADA_NL_CANDIDATE_FIRST=true`。
OCR 使用 `TEXADA_OCR_PREPROCESSING=raw`，保留尺寸、颜色和像素，只统一 PNG
编码。既有 profile 默认仍为二值化。该选择来自本次配对消融，不能代替原图审阅。

```text
文字 / 图片 / 补全
        ↓
MiniCPM-V-4.7-1B 候选
        ↓
FormulaState + Revision + Ledger
        ↓
同一个 4.7-1B Planner ↔ 确定性 TeX 工具
        ↓
当前 revision 的语法与渲染证据 → Commit Barrier → 用户审阅
```

`compile_tex` 是本项目的语法校验与 KaTeX AST 检查，不是完整 TeX 工程的 PDF 编译。
Commit Barrier 保证当前 revision 有检查证据，不能单独证明数学含义或 OCR 视觉忠实度。
本次不引入第二个裁判、OCR 模型或模型修复器。[ADR-017](adr/017-minicpm-v47-single-checkpoint.md)
记录部署决定。内置 llama-server 平台 PR #4 独立推进。

## API 启动

```sh
uv sync --extra dev --extra cas-eval
# 在进程环境中设置 TEXADA_OPENAI_API_KEY，避免把凭证写入命令脚本或 Git。
bash scripts/run-minicpm-v47.sh
```

脚本使用 `https://api.modelbest.cn/v1`，文本与视觉模型都固定为
`MiniCPM-V-4.7-1B`。已保存的桌面设置不会覆盖该进程环境。
`.env.example` 只展示变量；程序不会自动加载 `.env`。

设置页手动连接时选择 OpenAI-compatible，填写同一 endpoint 和两个相同模型名。
四条推理路径及其重试显式发送：

```json
{"chat_template_kwargs": {"enable_thinking": false}}
```

OCR 使用 `image_url` + PNG base64。V4.7 不发送原先的 `reasoning_effort: low`。
最终公式只从最终回答提取，隐藏推理和 `<think>` 内的公式不能作为候选答案。
标准 OpenAI `tool_calls` 沿用现有解析器。语法修复仍调用确定性的 `repair_tex`。

## 官方模型与本机 Q4

官方发布记录日期为 **2026-10-12**，本次核查日期为 **2026-10-13**。

| 用途 | 官方链接 |
|---|---|
| 本次单 checkpoint | [MiniCPM-V-4.7-1B](https://huggingface.co/openbmb/MiniCPM-V-4.7-1B) |
| Q4 / GGUF | [MiniCPM-V-4.7-1B-gguf](https://huggingface.co/openbmb/MiniCPM-V-4.7-1B-gguf) |
| 大模型参考 | [MiniCPM-V-4.7-35B-A3B](https://huggingface.co/openbmb/MiniCPM-V-4.7-35B-A3B) |

1B Q4_K_M 文件大小为 672,003,712 bytes，普通 F16 projector 为
1,110,117,984 bytes，两者下载约 1.78 GB；运行内存还包括上下文与工作缓冲区。
35B-A3B 的 A3B 表示激活参数，其 Q4 权重约 21.17 GB，另需 projector，
不作为本机 8GB 设备的路线。

权重清单来自实时 HF 元数据，尚未下载和校验本机权重：

```text
HF revision: 6ceac0238408005c4a1bbc779d9beb235ba71c57
MiniCPM-V-4_7-1B-Q4_K_M.gguf
SHA256: 00c18c51651d35f3f3447adc846350a7b1b665f5cec34827d3d6df8b31be765c
mmproj-model-f16.gguf
SHA256: fb9cc047a3cdad5317fd8433a4aeda2d22f00f02ca4bd93b34ad84165b25a900
```

llama.cpp 必须包含 [PR #29416](https://github.com/ggml-org/llama.cpp/pull/29416)。
本机当前 `b10150/dee2a846b` 位于该合入提交之前，已通过
[GitHub commit 比较](https://github.com/ggml-org/llama.cpp/compare/69f201a...dee2a846b)
确认，使用 Q4 前需要升级。
4.7 增加 `rope.section_order` 和 `v.tok_embd_sep`，旧转换器可能加载成功却计算错误。
直接下载官方 4.7 GGUF。以下是待本机权重验收的启动配置；不代表已实测 Q4 质量：

```sh
llama-server -m /path/to/MiniCPM-V-4_7-1B-Q4_K_M.gguf \
  --mmproj /path/to/mmproj-model-f16.gguf \
  --alias MiniCPM-V-4.7-1B --host 127.0.0.1 --port 8080 \
  --ctx-size 8192 --parallel 1 -ngl 99 --jinja --reasoning off
export TEXADA_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
export TEXADA_OPENAI_API_KEY=local-no-key
bash scripts/run-minicpm-v47.sh
```

不要使用模型默认的 256K 上下文启动 8GB 设备。先用单 slot、小上下文测量内存与
图像 token 预算，再调大。API 结果不能作为 Q4 精度、内存、速度或桌面安装包验收。

## 真实验收

```sh
uv run --no-sync python eval/run_minicpm_v47.py --output-dir /path/to/evidence
```

运行器默认测试候选优先链路，`--planner-control` 可重放原先的初始规划方式。
它使用同一黄金集与现有 matcher，每个模型请求至少间隔 3.2 秒；429 至多三次
尝试，间隔 30 秒，并保留限流事件。生产 SDK 仍保持零自动重试。
语义锚点指标只测包含关系，不是完整结构等价率。不可检查的条目与接口失败分开记录。
历史 28/95 是 MiniCPM5-2B 本机 Q4 的旧结果；API/权重精度/后端不同，不能据新结果
单独归因于模型升级。图像消融中的合成印刷公式也不能代表手写或真实页面质量。

正式记录见 [本次验收](minicpm-v47-evidence.md)。

官方来源：[发布记录](https://github.com/OpenBMB/MiniCPM-V)、
[API 说明](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/api.md)、
[llama.cpp 部署说明](https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/deployment/llama.cpp/minicpm-v4_7_llamacpp.md)。
