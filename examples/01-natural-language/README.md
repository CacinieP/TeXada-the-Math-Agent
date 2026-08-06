# 01 — Natural Language To Structured LaTeX

Input:

```text
probability density function
```

Validated output:

```tex
f_X(x)\ge 0,\quad \int_{-\infty}^{\infty}f_X(x)\,dx=1
```

![Natural language to a validated probability density formula](../../assets/demo/natural-language.gif)

This is a high-confidence structured concept. TeXada takes the zero-token
candidate path, but still records real `compile_tex` and `render_math`
observations in the Agent trace.
