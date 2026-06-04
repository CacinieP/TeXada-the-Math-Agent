"""
TeXada the Math Agent — Main entry point
Gemma 4 E4B via Ollama
"""

import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from agent import TeXadaAgent


def main():
    agent = TeXadaAgent()
    print("TeXada the Math Agent (type 'quit' to exit)")
    print("Enter math description in Chinese or English:\n")

    while True:
        try:
            user_input = input("📝 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        if not user_input:
            continue

        result = agent.convert(user_input)
        print(f"\n📐 LaTeX: {result.latex}")

        if result.matched_template:
            print(f"   (matched template: {result.matched_template})")

        if result.render_ok:
            print("   ✅ LaTeX syntax valid")
        else:
            print(f"   ⚠️  Validation issue: {result.render_error}")

        print()


if __name__ == "__main__":
    main()
