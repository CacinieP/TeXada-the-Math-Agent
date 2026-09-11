# MiniCPM5-2B local validation / 本机实测 — 2026-09-12

v0.4.1 replaces the default MiniCPM5-1B text/planner checkpoint
with MiniCPM5-2B Q4_K_M. This note records local integration measurements,
the failures that led to compatibility fixes, and the limits of the evidence.
The measurements were collected before the v0.4.1 installer release and
are not a separate acceptance report for the release artifacts.

中文摘要：在 A18 Pro、8GB 统一内存上，2B Q4_K_M 可以运行。最终六例开发用例平均
7.71 秒，全部通过编译、渲染和提交；严格结构匹配为 5/6，人工数学核对为 6/6。
这些题在开发中反复使用，不能据此声称通用准确率为 100%。本次只更新文本/规划模型，
没有验证 OCR；这里的实测发生在 v0.4.1 安装包发布之前。

## Environment and model

| Item | Recorded value |
|---|---|
| Machine | MacBook Neo, Apple A18 Pro, 6 CPU cores, 5 GPU cores, 8GB unified memory |
| OS / inference server | macOS 26.6.2 / Ollama 0.32.15 |
| Text model | `hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M` |
| GGUF size | 1,561,318,368 bytes; Ollama reports approximately 2.5B actual parameters |
| Context | `num_ctx 4096` in the imported Ollama model |
| Acceleration | Metal; Ollama reported all model residency on the GPU |
| Resident model size | 1,782,673,571 bytes, about 1.66 GiB, from `/api/ps`; not total process/system memory |
| Planner / formula output budgets | 2048 / 768 tokens |
| Planner turns | At most 3, followed by runtime validation/commit guards |
| Inference / request timeout | 90 / 240 seconds |
| Template | GGUF's native Jinja template, including native tool support |

The file was retrieved from the [OpenBMB ModelScope repository](https://modelscope.cn/models/OpenBMB/MiniCPM5-2B-GGUF)
at revision `7b592407d80c86fd561a9a02411a504b6bd96b88`. Its SHA-256 matched
the [official Hugging Face GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/tree/main):

```text
ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd
```

See [OpenBMB's llama.cpp deployment documentation](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/llama_cpp.md)
for the upstream model deployment path. The local validation used Ollama's
OpenAI-compatible API. For this tested server version, TeXada sends
`reasoning_effort: "none"` through the SDK's `extra_body` for local
MiniCPM5-2B text requests. A top-level `think: false` is not the corresponding
control for Ollama's OpenAI-compatible chat route. Native template rendering
was checked before real generation and tool tests.

## Method and aggregate results

Six synthetic cases exercised Chinese/English formula generation, completion
and a native planner/tool observation round trip. Preflight confirmed no case
bypassed the model through deterministic candidate rules. The harness called
the actual model wrapper and Agent Runtime with isolated configuration and
temporary data; it did not read personal history, presets or credentials.
The completion case used the completion wrapper followed by runtime validation.

| Path | Mean | Median | Strict structure match | Manual mathematical review | Valid and committed | Output-limit hits |
|---|---:|---:|---:|---:|---:|---:|
| Previous 1B path, default thinking | 38.587s | 35.337s | 1/6 | 1/6 | 3/6 | 4 |
| 1B control, thinking disabled | 13.388s | 4.387s | 1/6 | 1/6 | 5/6 | 1 |
| Final adapted 2B path, thinking disabled | 7.709s | 7.282s | 5/6 | 6/6 | 6/6 | 0 |

The final 2B run took 46.255 seconds across 17 real model calls. Strict scoring
compared semantic structure with expected formulas; compilation/rendering was
a separate gate. The piecewise output included extra “当……时” condition text,
so its strict tree differed despite preserving the requested mathematics.

These are full local request timings, not tokens/second. Each reported group
contains one run per case, without a controlled cold/warm reset between every
request. Model residency, sampling, thinking settings and runtime fixes vary
between groups. In particular, the 1B controls preceded the later division
and wrapper fixes. The table describes observed application paths; it does
not isolate model size as the cause of every difference.

## Final cases

| Case | Request / expected mathematics | Final latency | Strict match | Valid and committed |
|---|---|---:|---|---|
| Chinese nested sum | Sum from k=2 to m of `(a_k+b_k)/sqrt(k+1)` | 11.073s | Yes | Yes |
| Chinese piecewise | `h(t)=t²−1` for `t≥1`; `2t+3` for `t<1` | 10.075s | No: extra condition-label text | Yes |
| English derivative | `∂²u/∂x² + α∂u/∂t = 0` | 7.122s | Yes | Yes |
| English matrix | Square-bracket matrix `M`, rows `[a+b,c]` and `[d,e−f]` | 6.201s | Yes | Yes |
| Completion | Complete `\sin^2 x+\cos^2` | 7.442s | Yes | Yes |
| Planner round trip | Express the sum of a and b divided by c as a fraction | 4.342s | Yes | Yes |

The exact final outputs were:

```latex
\sum_{k=2}^{m} \frac{a_k + b_k}{\sqrt{k+1}}

h(t) = \begin{cases} t^2 - 1 & \text{当 } t \geq 1 \text{ 时} \\ 2t + 3 & \text{当 } t < 1 \text{ 时} \end{cases}

\frac{\partial^2 u}{\partial x^2} + \alpha \frac{\partial u}{\partial t} = 0

M = \begin{bmatrix} a + b & c \\ d & e - f \end{bmatrix}

\sin^2 x+\cos^2 x=1

\frac{a + b}{c}
```

The round-trip prompt explicitly asked the planner to call only `parse_tex`
first, wait for its observation, then compile and render. The final model
sequence was `parse_tex → parse_tex → compile_tex`; the runtime guard finished
the render/commit step. The trace verifies real tools and observation feedback,
not perfect model compliance with every requested step.

To inspect this path with a configured local build, submit a synthetic request
to the [Agent API](e2e-manual.md) and inspect `agent_trace`, `valid`, `committed`,
the semantic parser backend and `katex_html` together:

```bash
curl --noproxy '*' http://127.0.0.1:18732/api/agent \
  -H 'Content-Type: application/json' \
  --data '{"text":"请把 a 与 b 的和除以 c 写成分式。必须先只调用 parse_tex，再根据它返回的观察调用 compile_tex，最后调用 render_math。收到 parse_tex 的结果之前不要调用其他工具。","render_mode":"katex"}'
```

This uses the normal application API and saves a normal local run/history
entry. A different sample or server/model configuration may produce different
results; a successful render alone is not proof of mathematical fidelity.

## Failures and limitations retained in the record

- The initial 2B run had 6/6 valid commits but only 5/6 mathematically faithful
  outputs: “a 与 b 的和除以 c” became `a+b\div c`. Complete “除以” symbol matching
  and a narrow explicit-fraction anchor fixed the observed case. This anchor
  does not prove arbitrary grouping semantics or all Chinese negations.
- A later run had 5/6 valid commits because a planner tool argument wrapped a
  correct sum in `$…$`. KaTeX was already in math mode. Complete outer-wrapper
  normalization fixed this, with regressions for escaped dollars, embedded
  delimiters, multiple segments and the observed repeated-compile sequence.
  All six cases were rerun after the final fix, producing the table above.
- Early 1B instrumentation incorrectly treated `truncated = 0` log lines as
  truncation warnings. Rechecking the original lines found no actual context
  truncation in any group. Output-limit hits are different and are retained
  in the table.
- In a separate direct 2B probe, disabling thinking answered a two-dimensional
  Gaussian request with a general n-dimensional normalization without fixing
  n=2. Default thinking produced the correct two-dimensional form. The
  respective single-probe latencies were 1.962s and 18.601s. Lower latency
  therefore does not establish better accuracy on complex formulas.
- This is a repair-driven development set, not a held-out benchmark. No OCR
  performance or mathematical generalization claim follows from it. The
  configured MiniCPM-V model was absent and was not installed for this test.

## Source and desktop validation

The source change was developed from `ba65af784a8f0f8c27316305ad44e6b450d0fe04`.
Validation completed with **384 passing Python tests and 8 skipped tests**,
focused Ruff checks and `git diff --check`. Coverage includes SDK wire fields
for text/retry paths, unaffected OCR/other-model requests, Chinese operator
anchors, and full planner-tool compile/render/commit regressions.

The local desktop check retained the existing 0.3.8 shell and rebuilt its
bundled backend from then-current 0.4.0 source plus these changes. Strict recursive
code-signature validation passed. Native UI inspection showed the 2B model
and `Text ready · OCR missing`. Subsequent UI automation timed out, so the
final generation check called the installed app's automatically started
backend directly: the nested sum returned `valid=true`, `committed=true`,
a KaTeX semantic document and nonempty KaTeX HTML in 13.704 seconds. It did
not use a development server from the test worktree. This check does not
constitute a completed visual inspection of that final rendered formula.

Existing saved settings are not silently migrated by changing the source
default. Select the 2B model in Settings when upgrading; retain the separate
vision setting for OCR. Upgrade older installers to v0.4.1 to receive the
model compatibility fixes; changing a model setting alone does not update code.
