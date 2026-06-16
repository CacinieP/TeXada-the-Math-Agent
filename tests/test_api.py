"""Smoke test for the FastAPI app — guards against missing-dependency crashes.

Regression: ``/api/ocr`` uses ``UploadFile`` which requires ``python-multipart``
at import time. Without that dependency declared, ``create_app()`` raised
``RuntimeError: Form data requires "python-multipart"`` and the whole server
could not start. This test constructs the app and inspects its routes.
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_create_app_builds_all_routes():
    from texada.api import create_app

    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    # Every endpoint the frontend (tauri-shell/src/main.js) calls must exist.
    expected = {
        "/api/status",
        "/api/convert",
        "/api/complete",
        "/api/ocr",  # the route that needs python-multipart
        "/api/validate",
        "/api/render-mode",
        "/api/shorthands",
        "/api/history",
    }
    missing = expected - paths
    assert not missing, f"Missing API routes: {missing}"


async def test_api_version_matches_pyproject():
    """The FastAPI app version should match the package version in pyproject.toml."""
    import importlib.metadata

    from texada.api import create_app

    app = create_app()
    package_version = importlib.metadata.version("texada")
    assert app.version == package_version, (
        f"FastAPI app version {app.version!r} != installed texada {package_version!r}"
    )
