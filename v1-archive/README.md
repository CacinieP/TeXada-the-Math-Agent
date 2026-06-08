# TeXada the Math Agent

> Local math formula agent powered by **Gemma 4 E4B** — boost your note-taking speed.

## What it does

| Input | Output | Example |
|-------|--------|---------|
| Natural language | LaTeX | `"二重积分 f(x,y) 在 D 上"` → `\iint_D f(x,y)\,dx\,dy` |
| Screenshot / image | LaTeX | Photo of blackboard formula → LaTeX |
| Partial LaTeX | Completion | `\sum_{i=1}^{` → `\sum_{i=1}^{n} x_i` |
| Custom shorthand | Full formula | `"euler"` → `e^{i\pi}+1=0` |

## Architecture

```
Input (text/image) → Intent Router → Symbol Dict + Template → Gemma 4 E4B → LaTeX Validation → Clipboard/TSF
```

**Key principle:** Symbol lookup, template filling, and syntax validation are handled by deterministic code. The LLM only handles ambiguous natural language understanding — which a 4B model does well.

## Tech Stack

- **LLM:** Gemma 4 E4B via Ollama (local inference)
- **Backend:** Python + FastAPI
- **LaTeX validation:** sympy + KaTeX
- **Image preprocessing:** OpenCV
- **Output:** Clipboard / TeXada TSF integration

## Quick Start

```bash
# Ensure Ollama is running with gemma4:e4b
ollama list

# Install dependencies
pip install -r requirements.txt

# Run the agent
python main.py
```

## License

Private repository.
