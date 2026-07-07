"""TeXada CLI + API entry point."""
import typer

app = typer.Typer(help="TeXada — Math Formula Agent")


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind host. Defaults to TEXADA_API_HOST/config."),
    port: int | None = typer.Option(None, help="Bind port. Defaults to TEXADA_API_PORT/config."),
):
    """Start the FastAPI backend server."""
    import uvicorn

    from texada.api import create_app
    from texada.config import load_config

    config = load_config()

    # Force the asyncio event loop (not uvloop). uvicorn[standard] pulls in
    # uvloop by default, which deadlocks when launched as a background
    # LaunchAgent (no TTY, Aqua session) — the server process stays alive
    # but never finishes startup and never binds the port. asyncio works
    # identically under both an interactive shell and launchd.
    uvicorn.run(
        create_app(config),
        host=host or config.api_host,
        port=port or config.api_port,
        loop="asyncio",
    )


@app.command()
def convert(text: str):
    """Convert a single natural language input to LaTeX."""
    import asyncio

    from texada.config import load_config
    from texada.core.router import InputRouter

    config = load_config()
    router = InputRouter(config)
    result = asyncio.run(router.process_text(text))
    typer.echo(result.latex)


@app.command()
def check():
    """Check system readiness — Ollama daemon, model, dependencies."""
    import asyncio

    from texada.config import load_config
    from texada.core.backend import BackendManager

    config = load_config()
    mgr = BackendManager(config)

    typer.echo("TeXada v0.3.0 — System Check")
    typer.echo(f"  Backend:      {config.backend}")
    typer.echo(f"  Endpoint:     {config.active_base_url}")
    typer.echo(f"  Model:        {config.active_model_name}")
    typer.echo(f"  Vision model: {config.active_vision_model_name}")

    try:
        asyncio.run(mgr.ensure_ready())
        typer.echo("  Status:       ✅ ready")
    except Exception as e:
        typer.echo(f"  Status:       ❌ {e}")

    typer.echo(f"  Render mode:  {config.default_render_mode}")
    typer.echo(f"  Delimiter:    {config.delimiter}")


if __name__ == "__main__":
    app()
