# TeXada 运行日志

此目录存放 TeXada 的运行截图和日志，供评审复现参考。

## 示例运行日志

### 系统检查

```
$ texada check
TeXada v0.2.0 — System Check
  Ollama host:  http://localhost:11434
  Model:        gemma4:e4b-it-qat
  Ollama:       ✅ running
  Model loaded: ✅ gemma4:e4b-it-qat
  Render mode:  katex
  Delimiter:    $$
```

### NL→LaTeX 转换（含 Tool Calling）

```
Input:  "二重积分 f(x,y) 在区域 D 上"
Route:  nl2latex
Intent: integral (confidence: 0.9)
Pre-translate: "\iint f(x,y) 在区域 D 上"

[Tool Calling Loop]
  → Tool: lookup_symbol("区域") → "No exact match for '区域'. Use standard LaTeX command."
  → Tool: validate_latex("\iint_D f(x,y)\,dx\,dy") → "Valid LaTeX."

Output: \iint_D f(x,y)\,dx\,dy
Valid:  ✅
Source: model
Latency: 1842ms
```

### LaTeX 补全

```
Input:  "\sum_{i=1}^{"
Route:  completion (auto-detected: contains \command)
Output: \sum_{i=1}^{n} x_i
Valid:  ✅
Latency: 892ms
```

### 快捷公式

```
Input:  "euler"
Route:  shorthand (exact match)
Output: e^{i\pi}+1=0
Valid:  ✅
Latency: <1ms
```

### OCR 图片识别

```
Input:  [手写积分公式图片]
Route:  ocr
Output: \int_0^1 x^2\,dx
Valid:  ✅
Latency: 3241ms
```

---

*截图待补充：运行时将终端输出截图放入此目录。*
