"""TeXada CLI entry point — v2 skeleton."""
import typer

app = typer.Typer(help="TeXada — Math Formula Agent")

@app.command()
def main():
    """Launch TeXada interactive session."""
    typer.echo("TeXada v0.2.0 — Gemma 4 E4B Math Agent")
    typer.echo("Not yet implemented. See docs/design.md for architecture.")

if __name__ == "__main__":
    app()
