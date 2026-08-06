# 02 — Handwritten Formula OCR

Input:

![Handwritten definite integral used by the OCR demo](../../assets/demo/ocr-integral-input.png)

Validated output:

```tex
\int_0^1 x^2\,dx
```

![Handwritten formula to structured LaTeX](../../assets/demo/image-ocr.gif)

MiniCPM-V 4.6 proposes the OCR candidate. The shared Agent runtime then
compiles and renders the candidate before TeXada marks it valid.
