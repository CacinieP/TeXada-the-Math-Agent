# Why TeXada?

TeXada is for a specific workflow: turn natural language, formula images, and
incomplete LaTeX into structured math on your machine, then validate the
syntax before rendering. It is not intended to replace a general assistant, a
full collaborative LaTeX platform, or a dedicated document-OCR service.

## Product Focus

| Product | Primary workflow | Formula image input | LaTeX error path | Local/open runtime |
|---------|------------------|---------------------|------------------|--------------------|
| **TeXada** | Local structured math editor with one tool-using planner | MiniCPM-V candidate reviewed by the shared Agent runtime | Deterministic bounded repair, compile check, render check, and trace | Local Ollama path; AGPL-3.0-or-later |
| **ChatGPT** | General conversational assistant | General image inputs | Conversational help; not a dedicated LaTeX compile/repair trace | Hosted product |
| **Overleaf AI** | Collaborative online LaTeX and academic-writing environment | Equation generation from an image or prompt | Error Assist explains and suggests fixes inside the editor | Hosted editor; some AI features use third-party services |
| **Mathpix Snip** | STEM OCR, capture, conversion, and export | Core product strength for printed and handwritten math | Edit/export workflow rather than TeXada's planner/tool/compiler trace | Hosted OCR-backed product |

The useful distinction is not "which product has AI?" All four do. The
distinction is where the center of gravity sits:

- Choose **TeXada** when local execution, inspectable formula tools, and a
  narrow structured-math workflow matter most.
- Choose **ChatGPT** when the task is broad conversation, explanation, or
  general multimodal reasoning.
- Choose **Overleaf** when real-time collaboration and full-document LaTeX
  authoring are the priority.
- Choose **Mathpix** when high-coverage OCR and document conversion are the
  primary job.

## Sources And Scope

This comparison describes advertised product focus, not a benchmark score.
Features and plans change; the links below are the authoritative references.

- [TeXada architecture](architecture.md)
- [ChatGPT image inputs](https://help.openai.com/en/articles/8400551-chatgpt-image-inputs-faq/)
- [Overleaf AI features](https://docs.overleaf.com/integrations-and-add-ons/ai-features)
- [Overleaf Error Assist](https://docs.overleaf.com/integrations-and-add-ons/ai-features/error-assist)
- [Mathpix equation to LaTeX](https://website.mathpix.com/equation-to-latex)
- [Mathpix image to LaTeX](https://website.mathpix.com/image-to-latex)
