"""Smoke test for the FastAPI app — guards against missing-dependency crashes.

Regression: ``/api/ocr`` uses ``UploadFile`` which requires ``python-multipart``
at import time. Without that dependency declared, ``create_app()`` raised
``RuntimeError: Form data requires "python-multipart"`` and the whole server
could not start. This test constructs the app and inspects its routes.
"""
import pytest
from fastapi.testclient import TestClient

from texada.agent.runtime import AgentRunResult, TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.router import InputRouter
from texada.render.engine import RenderEngine
from texada.types import RenderMode

pytestmark = pytest.mark.asyncio


async def test_create_app_builds_all_routes():
    from texada.api import create_app

    app = create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    # Every endpoint the frontend (tauri-shell/src/main.js) calls must exist.
    expected = {
        "/api/status",
        "/api/agent",
        "/api/convert",
        "/api/complete",
        "/api/ocr",  # the route that needs python-multipart
        "/api/validate",
        "/api/render-mode",
        "/api/shorthands",
        "/api/shorthands/export",
        "/api/shorthands/import",
        "/api/history",
        "/api/history/export",
        "/api/history/import",
        "/api/runs",
        "/api/runs/export",
        "/api/runs/import",
        "/api/runs/{run_id}",
        "/api/export",
        "/api/import",
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


async def test_completion_endpoint_runs_candidate_through_agent(
    tmp_path,
    monkeypatch,
):
    from texada.api import create_app

    config = TeXadaConfig(data_dir=tmp_path)
    captured = {}

    async def fake_candidate(self, text, *, context=""):
        captured["candidate_request"] = (text, context)
        return r"\sum_{i=1}^{n} i", 5

    async def fake_run_candidate(
        self,
        task,
        user_input,
        candidate_latex,
        **kwargs,
    ):
        captured["agent_request"] = (
            task,
            user_input,
            candidate_latex,
            kwargs,
        )
        return AgentRunResult(
            latex=candidate_latex,
            valid=True,
            render=RenderEngine(config).render(
                candidate_latex,
                mode_override=RenderMode.KATEX,
            ),
            semantic_document={"latex": candidate_latex},
            trace=[
                {
                    "step": 1,
                    "origin": "candidate_intake",
                    "tool_calls": [{"name": "compile_tex"}],
                    "observations": [
                        {"tool": "compile_tex", "ok": True, "output": {"valid": True}}
                    ],
                }
            ],
            tokens_used=8,
            stop_reason="planner_final",
        )

    monkeypatch.setattr(
        InputRouter,
        "create_completion_candidate",
        fake_candidate,
    )
    monkeypatch.setattr(
        TeXadaAgentRuntime,
        "run_candidate",
        fake_run_candidate,
    )
    client = TestClient(create_app(config))

    response = client.post(
        "/api/complete",
        json={
            "text": r"\sum_{i=1}^{",
            "context": "sequence",
            "render_mode": "katex",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "agent"
    assert body["intent"] == "completion_agent"
    assert body["agent_trace"][0]["origin"] == "candidate_intake"
    assert captured["candidate_request"] == (r"\sum_{i=1}^{", "sequence")
    assert captured["agent_request"][0] == "completion"
    assert captured["agent_request"][3]["initial_tokens_used"] == 5
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["model_role"] == "planner"
    assert run["tool_names"] == ["compile_tex"]
    assert run["trace"]


async def test_agent_endpoint_returns_invalid_candidate_with_trace(
    tmp_path,
    monkeypatch,
):
    from texada.api import create_app

    config = TeXadaConfig(data_dir=tmp_path)
    invalid_latex = "..."
    trace = [
        {
            "step": 1,
            "origin": "runtime_guard",
            "content": invalid_latex,
            "tool_calls": [],
            "observations": [
                {
                    "tool": "compile_tex",
                    "ok": True,
                    "output": {
                        "valid": False,
                        "diagnostics": [
                            {
                                "type": "non_formula_content",
                                "detail": "输出只有省略号，不是可用的数学公式",
                                "error": "",
                            }
                        ],
                    },
                }
            ],
        }
    ]

    async def fake_run(self, text, **kwargs):
        return AgentRunResult(
            latex=invalid_latex,
            valid=False,
            render=RenderEngine(config).render(
                invalid_latex,
                mode_override=RenderMode.KATEX,
            ),
            semantic_document={"latex": invalid_latex},
            trace=trace,
            tokens_used=12,
            stop_reason="validation_failed_after_repair",
        )

    monkeypatch.setattr(TeXadaAgentRuntime, "run", fake_run)
    client = TestClient(create_app(config))

    response = client.post(
        "/api/agent",
        json={"text": "unknown request", "render_mode": "katex"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["latex"] == invalid_latex
    assert body["agent_trace"] == trace
    assert body["stop_reason"] == "validation_failed_after_repair"
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["status"] == "success"
    assert run["valid"] is False
    assert run["output_latex"] == invalid_latex
    assert run["trace"] == trace


async def test_ocr_endpoint_runs_vision_candidate_through_agent(
    tmp_path,
    monkeypatch,
):
    from texada.api import create_app

    config = TeXadaConfig(data_dir=tmp_path)
    captured = {}

    async def fake_candidate(self, image):
        captured["image"] = image
        return r"x^2+y^2", 7

    async def fake_run_candidate(
        self,
        task,
        user_input,
        candidate_latex,
        **kwargs,
    ):
        captured["agent_request"] = (
            task,
            user_input,
            candidate_latex,
            kwargs,
        )
        return AgentRunResult(
            latex=candidate_latex,
            valid=True,
            render=RenderEngine(config).render(
                candidate_latex,
                mode_override=RenderMode.KATEX,
            ),
            semantic_document={"latex": candidate_latex},
            trace=[
                {
                    "step": 1,
                    "origin": "candidate_intake",
                    "tool_calls": [{"name": "compile_tex"}],
                    "observations": [
                        {"tool": "compile_tex", "ok": True, "output": {"valid": True}}
                    ],
                }
            ],
            tokens_used=10,
            stop_reason="planner_final",
        )

    monkeypatch.setattr(InputRouter, "create_ocr_candidate", fake_candidate)
    monkeypatch.setattr(
        TeXadaAgentRuntime,
        "run_candidate",
        fake_run_candidate,
    )
    client = TestClient(create_app(config))

    response = client.post(
        "/api/ocr",
        files={"image": ("formula.png", b"png-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "agent"
    assert body["intent"] == "ocr_agent"
    assert body["agent_trace"][0]["origin"] == "candidate_intake"
    assert captured["image"] == b"png-bytes"
    assert captured["agent_request"][0] == "ocr"
    assert captured["agent_request"][3]["initial_tokens_used"] == 7
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["model_role"] == "planner"
    assert "->" in run["model_name"]
    assert run["trace"]


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


async def test_shorthand_api_protects_builtins_and_rejects_prose(tmp_path):
    from texada.api import create_app

    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))

    builtin = client.post(
        "/api/shorthands",
        json={"key": "euler", "value": "x"},
    )
    prose = client.post(
        "/api/shorthands",
        json={"key": "bad", "value": "这不是一个公式"},
    )

    assert builtin.status_code == 409
    assert prose.status_code == 422
    presets = {item["key"]: item["value"] for item in client.get("/api/shorthands").json()}
    assert presets["euler"] == "e^{i\\pi}+1=0"
    assert "bad" not in presets


async def test_history_endpoint_filters_by_type_and_query(tmp_path):
    from texada.api import create_app
    from texada.store.history import HistoryStore
    from texada.types import HistoryEntry

    config = TeXadaConfig(data_dir=tmp_path)
    store = HistoryStore(config)
    await store.add(HistoryEntry(
        input_text="integral of x",
        input_type="nl",
        latex="\\int x \\, dx",
        intent="integral",
        source="model",
        render_mode="katex",
        valid=True,
        latency_ms=22.0,
    ))
    await store.add(HistoryEntry(
        input_text="\\sum_{i=1}^{",
        input_type="completion",
        latex="\\sum_{i=1}^{n} i",
        intent="completion",
        source="model",
        render_mode="katex",
        valid=True,
        latency_ms=12.0,
    ))

    app = create_app(config)
    client = TestClient(app)

    response = client.get("/api/history?q=sum&type=completion")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["input_type"] == "completion"
    assert body[0]["input_text"] == "\\sum_{i=1}^{"


async def test_history_export_import_and_clear_endpoints(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)
    payload = {
        "mode": "merge",
        "history": [
            {
                "input_text": "integral",
                "input_type": "nl",
                "latex": "\\int x\\,dx",
                "intent": "integral",
                "source": "model",
                "render_mode": "katex",
                "valid": True,
                "latency_ms": 1.0,
                "created_at": "2026-07-20 10:00:00",
            }
        ],
    }

    import_response = client.post(
        "/api/history/import",
        json=payload,
    )

    assert import_response.status_code == 200
    assert import_response.json()["imported"] == 1

    duplicate_response = client.post(
        "/api/history/import",
        json=payload,
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["skipped"] == 1

    export_response = client.get("/api/history/export")
    body = export_response.json()
    assert export_response.status_code == 200
    assert body["_meta"]["schema_version"] == 2
    assert body["history"][0]["input_text"] == "integral"

    clear_response = client.delete("/api/history?type=nl")

    assert clear_response.status_code == 200
    assert clear_response.json()["deleted"] == 1
    assert client.get("/api/history/export").json()["history"] == []


async def test_full_backup_export_import_excludes_api_key(tmp_path):
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
    client.post("/api/shorthands", json={"key": "mine", "value": "y^2"})
    client.post(
        "/api/history/import",
        json={
            "history": [
                {
                    "input_text": "sum",
                    "input_type": "nl",
                    "latex": "\\sum_i x_i",
                }
            ]
        },
    )

    backup = client.get("/api/export").json()

    assert "openai_api_key" not in backup["settings"]
    assert backup["settings"]["openai_base_url"] == "https://example.test/v1"
    assert backup["shorthands"] == {"mine": "y^2"}
    assert len(backup["history"]) == 1

    imported = client.post(
        "/api/import",
        json={
            "mode": "merge",
            "settings": {"ui_language": "en", "openai_api_key": "ignored"},
            "shorthands": {"custom2": "z^2", "euler": "bad"},
            "history": backup["history"],
        },
    )

    assert imported.status_code == 200
    body = imported.json()
    assert body["settings"]["imported"] == 1
    assert body["shorthands"] == {"imported": 1, "skipped": 1, "cleared": 0}
    assert client.get("/api/settings/ui").json()["ui_language"] == "en"


async def test_invalid_backup_settings_fail_before_any_data_is_mutated(tmp_path):
    from texada.api import create_app

    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))
    assert client.post(
        "/api/shorthands",
        json={"key": "old-preset", "value": "x^2"},
    ).status_code == 200
    assert client.post(
        "/api/history/import",
        json={
            "history": [
                {
                    "run_id": "old-run",
                    "input_text": "old",
                    "latex": "x",
                }
            ]
        },
    ).status_code == 200

    response = client.post(
        "/api/import",
        json={
            "mode": "replace",
            "settings": {"temperature": 99},
            "shorthands": {"new-preset": "y^2"},
            "history": [
                {
                    "run_id": "new-run",
                    "input_text": "new",
                    "latex": "y",
                }
            ],
        },
    )

    assert response.status_code == 422
    presets = {item["key"] for item in client.get("/api/shorthands").json()}
    assert "old-preset" in presets
    assert "new-preset" not in presets
    history = client.get("/api/history/export").json()["history"]
    assert [entry["run_id"] for entry in history] == ["old-run"]


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


async def test_backend_settings_expose_and_persist_request_timeouts(tmp_path):
    from texada.api import create_app

    app = create_app(TeXadaConfig(data_dir=tmp_path))
    client = TestClient(app)

    defaults = client.get("/api/settings/backend")
    assert defaults.status_code == 200
    assert defaults.json()["inference_timeout_seconds"] == 90.0
    assert defaults.json()["api_request_timeout_seconds"] == 240.0

    response = client.post(
        "/api/settings/backend",
        json={
            "inference_timeout_seconds": 135,
            "api_request_timeout_seconds": 360,
        },
    )

    assert response.status_code == 200
    assert response.json()["inference_timeout_seconds"] == 135.0
    assert response.json()["api_request_timeout_seconds"] == 360.0
    persisted = client.get("/api/settings/backend").json()
    assert persisted["inference_timeout_seconds"] == 135.0
    assert persisted["api_request_timeout_seconds"] == 360.0


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
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host="localhost:11435",
    )

    assert config.ollama_host == "http://localhost:11435"
    assert config.active_base_url == "http://localhost:11435/v1"


async def test_ollama_host_strips_openai_suffix(tmp_path):
    config = TeXadaConfig(
        data_dir=tmp_path,
        backend="ollama",
        ollama_host="http://localhost:11435/v1",
    )

    assert config.ollama_host == "http://localhost:11435"
    assert config.active_base_url == "http://localhost:11435/v1"


async def test_agent_endpoint_exposes_trace_and_semantic_document(tmp_path, monkeypatch):
    config = TeXadaConfig(data_dir=tmp_path)
    render = RenderEngine(config).render(r"\frac{a}{b}")

    async def fake_run(self, user_input, *, context="", render_mode=None):
        return AgentRunResult(
            latex=r"\frac{a}{b}",
            valid=True,
            render=render,
            semantic_document={
                "latex": r"\frac{a}{b}",
                "root": {"kind": "sequence"},
            },
            trace=[{"step": 1, "origin": "planner"}],
            semantic_diff={"equivalent": True, "change_count": 0},
            tokens_used=9,
            latency_ms=12.5,
            stop_reason="planner_final",
        )

    monkeypatch.setattr(TeXadaAgentRuntime, "run", fake_run)

    from texada.api import create_app

    response = TestClient(create_app(config)).post(
        "/api/agent",
        json={"text": "a divided by b", "render_mode": "katex"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["latex"] == r"\frac{a}{b}"
    assert body["source"] == "agent"
    assert body["semantic_document"]["root"]["kind"] == "sequence"
    assert body["agent_trace"][0]["origin"] == "planner"
    assert body["stop_reason"] == "planner_final"
