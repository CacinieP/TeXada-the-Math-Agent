"""Packaged FastAPI sidecar entry point for desktop installers."""
from __future__ import annotations


def main() -> None:
    """Start the TeXada FastAPI backend for the bundled desktop shell."""
    import uvicorn

    from texada.api import create_app
    from texada.config import load_config

    config = load_config()
    uvicorn.run(
        create_app(config),
        host=config.api_host,
        port=config.api_port,
        loop="asyncio",
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
