"""Smoke test for the FastAPI app — guards against missing-dependency crashes.

Regression: ``/api/ocr`` uses ``UploadFile`` which requires ``python-multipart``
at import time. Without that dependency declared, ``create_app()`` raised
``RuntimeError: Form data requires "python-multipart"`` and the whole server
could not start. This test constructs the app and inspects its routes.
"""
import pytest
from fastapi.testclient import TestClient

from texada.config import TeXadaConfig

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
        "/api/settings/backend",
        "/api/settings/ui",
        "/api/runtime",
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


async def test_forbidden_browser_origin_is_rejected(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    response = client.get("/api/status", headers={"Origin": "https://example.invalid"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden origin"


async def test_allowed_browser_origin_gets_cors_header(tmp_path):
    from texada.api import create_app

    origin = "http://127.0.0.1:5173"
    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    response = client.get("/api/status", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_runtime_config_uses_server_config(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path, api_host="localhost", api_port=19001))
    client = TestClient(app)

    response = client.get("/api/runtime")

    assert response.status_code == 200
    body = response.json()
    assert body["api_base_url"] == "http://localhost:19001"
    assert body["max_ocr_bytes"] > 0
    assert "image/png" in body["allowed_image_mime_types"]


async def test_ocr_upload_size_limit(tmp_path):
    from texada.api import create_app

    config = TeXadaConfig(data_dir=tmp_path, max_ocr_bytes=3)
    app = create_app(config)
    client = TestClient(app)

    response = client.post(
        "/api/ocr",
        files={"image": ("formula.png", b"1234", "image/png")},
    )

    assert response.status_code == 413


async def test_shorthand_list_marks_editable_items(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    client.post("/api/shorthands", json={"key": "custom", "value": "x^2"})
    response = client.get("/api/shorthands")

    assert response.status_code == 200
    items = {item["key"]: item for item in response.json()}
    assert items["euler"]["editable"] is False
    assert items["custom"]["editable"] is True


async def test_backend_settings_do_not_echo_key(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/settings/backend",
        json={
            "backend": "openai_compatible",
            "openai_base_url": "https://example.test/v1",
            "openai_model_name": "custom-model",
            "openai_api_key": "secret-key",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "openai_compatible"
    assert body["openai_api_key_set"] is True
    assert "openai_api_key" not in body


async def test_backend_settings_key_is_preserved_when_blank(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    client.post(
        "/api/settings/backend",
        json={
            "backend": "openai_compatible",
            "openai_base_url": "https://example.test/v1",
            "openai_model_name": "model-a",
            "openai_api_key": "secret-key",
        },
    )
    response = client.post(
        "/api/settings/backend",
        json={
            "backend": "openai_compatible",
            "openai_base_url": "https://example.test/v1",
            "openai_model_name": "model-b",
            "openai_api_key": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["openai_api_key_set"] is True


async def test_ui_language_setting_is_persisted(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    response = client.post("/api/settings/ui", json={"ui_language": "en"})

    assert response.status_code == 200
    assert response.json()["ui_language"] == "en"
    assert client.get("/api/settings/ui").json()["ui_language"] == "en"


async def test_ui_zoom_setting_is_persisted(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    response = client.post("/api/settings/ui", json={"ui_zoom": 1.2})

    assert response.status_code == 200
    assert response.json()["ui_zoom"] == 1.2
    assert client.get("/api/settings/ui").json()["ui_zoom"] == 1.2


async def test_ollama_host_accepts_custom_port_without_scheme(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path, ollama_host="localhost:11435")

    assert config.ollama_host == "http://localhost:11435"
    assert config.active_base_url == "http://localhost:11435/v1"


async def test_ollama_host_strips_openai_suffix(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path, ollama_host="http://localhost:11435/v1")

    assert config.ollama_host == "http://localhost:11435"
    assert config.active_base_url == "http://localhost:11435/v1"
