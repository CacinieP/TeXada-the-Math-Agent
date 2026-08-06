# 03 — Repair An Incomplete Gaussian PDF

Input:

```tex
f(x)=\frac{1}{\sigma\sqrt{2\pi}}e^{-\frac{(x-\mu)^2}{2\sigma^2
```

Repaired and validated output:

```tex
f(x)=\frac{1}{\sigma\sqrt{2\pi}}e^{-\frac{(x-\mu)^2}{2\sigma^2}}
```

![Incomplete Gaussian probability density formula repaired and rendered](../../assets/demo/latex-repair.gif)

The missing closing groups are a bounded syntax error. TeXada repairs them
deterministically, recompiles the candidate, and renders the valid formula. It
does not invent missing mathematical terms or claim to correct arbitrary
mathematical meaning.
