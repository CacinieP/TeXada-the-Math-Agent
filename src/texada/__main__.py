"""TeXada CLI + API entry point."""
import typer

app = typer.Typer(help="TeXada — Math Formula Agent")


@app.command()
def serve():
    """Start the FastAPI backend server."""
    from texada.api import create_app
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=18732)


@app.command()
def convert(text: str):
    """Convert a single natural language input to LaTeX."""
    import asyncio
    from texada.core.router import InputRouter
    from texada.config import load_config

    config = load_config()
    router = InputRouter(config)
    result = asyncio.run(router.process_text(text))
    typer.echo(result.latex)


@app.command()
def check():
    """Check system readiness — Ollama daemon, model, dependencies."""
    import asyncio
    from texada.core.backend import BackendManager
    from texada.config import load_config

    config = load_config()
    mgr = BackendManager(config)

    typer.echo("TeXada v0.2.0 — System Check")
    typer.echo(f"  Ollama host:  {config.ollama_host}")
    typer.echo(f"  Backend:      ollama")
    typer.echo(f"  Model:        {config.model_name}")
    typer.echo(f"  Vision model: {config.vision_model_name}")

    try:
        asyncio.run(mgr.ensure_ready())
        typer.echo(f"  Ollama:       ✅ running")
    except Exception as e:
        typer.echo(f"  Text server:  ❌ {e}")

    typer.echo(f"  Render mode:  {config.default_render_mode}")
    typer.echo(f"  Delimiter:    {config.delimiter}")


if __name__ == "__main__":
    app()