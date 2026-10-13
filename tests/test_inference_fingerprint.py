"""Production collection hooks, privacy, stable identity, and API correlation."""

import asyncio
import copy
import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import InternalServerError, OpenAI
from pydantic import ValidationError

from texada.agent.runtime import AgentRunResult, TeXadaAgentRuntime
from texada.api import RunLogImportEntry, create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.inference_fingerprint import (
    InferenceCollector,
    build_inference_identity,
    canonical_sha256,
    collect_inference,
    current_inference_collector,
    legacy_inference_fingerprint,
    sanitized_endpoint,
    validate_inference_fingerprint,
)
from texada.core.model import MiniCPMModel
from texada.core.router import InputRouter
from texada.render.engine import RenderEngine
from texada.types import ConvertResult, Source


def api_config(tmp_path, **updates):
    return TeXadaConfig(**{
        "data_dir": tmp_path, "backend": "openai_compatible",
        "openai_base_url": "https://api.example.test/v1",
        "openai_api_key": "test-secret-key",
        "openai_model_name": "MiniCPM-V-4.7-1B",
        "openai_vision_model_name": "", **updates,
    })


def provider_response(content="x", model="provider-model", fingerprint="provider-fingerprint"):
    return {
        "id": "fake", "object": "chat.completion", "created": 0, "model": model,
        "system_fingerprint": fingerprint,
        "choices": [{
            "index": 0, "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


def mock_provider(model, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model._client = OpenAI(
        base_url="https://api.example.test/v1", api_key="test-secret-key",
        http_client=client, max_retries=0,
    )
    return client


def test_stable_identity_excludes_secrets_and_tracks_all_critical_configuration(tmp_path):
    config = api_config(
        tmp_path, openai_base_url="https://alice:url-password@api.example.test/v1?token=query-secret#x",
    )
    identity = build_inference_identity(config)
    assert identity["endpoint"] == "https://api.example.test/v1"
    alternate = api_config(
        tmp_path, openai_api_key="another-secret",
        openai_base_url="https://bob:other-password@api.example.test/v1?token=different#other",
    )
    assert identity == build_inference_identity(alternate)
    serialized = json.dumps(identity)
    for private in ("test-secret-key", "url-password", "query-secret", "alice", "token="):
        assert private not in serialized
    for updates in (
        {"temperature": 0.2}, {"max_tokens": 512}, {"nl_candidate_first": True},
        {"ocr_preprocessing": "raw"}, {"openai_model_name": "other-checkpoint"},
        {"inference_timeout_seconds": 30}, {"agent_max_steps": 4},
    ):
        assert canonical_sha256(build_inference_identity(api_config(tmp_path, **updates))) != (
            canonical_sha256(identity)
        )
    assert build_inference_identity(config, prompt_manifest={"prompt": "changed"}) != identity
    assert build_inference_identity(config, tool_schemas=[]) != identity
    assert build_inference_identity(config, dataset_version="fixture-v2") != identity
    assert build_inference_identity(api_config(
        tmp_path, backend="ollama", model_name="external-q4-alias",
    ))["backend"] == "ollama"


def test_hidden_artifacts_are_not_inferred_from_q4_alias_or_provider_gateway(tmp_path):
    identity = build_inference_identity(api_config(tmp_path, openai_model_name="local-Q4_K_M"))
    for evidence in identity["artifacts"].values():
        assert evidence["status"] == "NOT_CHECKED"
        assert evidence["value"] is None
        assert evidence["reason"]
    assert identity["application_build"]["status"] == "NOT_CHECKED"
    assert identity["dataset"]["version"]["status"] == "NOT_CHECKED"
    assert sanitized_endpoint("https://user:secret@[::1]:8080/v1?q=secret") == (
        "https://[::1]:8080/v1"
    )


def test_import_rejects_added_secret_fields_url_secrets_and_false_identity_digests(tmp_path):
    fingerprint = InferenceCollector(build_inference_identity(api_config(tmp_path))).snapshot()
    assert validate_inference_fingerprint(fingerprint) == fingerprint
    for mutate in (
        lambda value: value.update(api_key="must-not-persist"),
        lambda value: value["identity"].update(endpoint="https://user:secret@host/v1?q=secret"),
        lambda value: value["identity"].update(backend="unsupported"),
        lambda value: value.update(identity_sha256="0" * 64),
    ):
        altered = copy.deepcopy(fingerprint)
        mutate(altered)
        with pytest.raises(ValidationError):
            RunLogImportEntry(run_id="bad-import", inference_fingerprint=altered)
    assert RunLogImportEntry(run_id="old-import").inference_fingerprint == (
        legacy_inference_fingerprint()
    )


@pytest.mark.asyncio
async def test_actual_sdk_attempts_report_identity_and_retry_without_tools(tmp_path):
    config = api_config(tmp_path)
    model = MiniCPMModel(config)
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {
                "message": "tools not supported", "type": "invalid_request_error",
                "code": "unsupported_parameter",
            }})
        return httpx.Response(200, json=provider_response())

    http_client = mock_provider(model, handler)
    try:
        with collect_inference(build_inference_identity(config)) as collector:
            await model.plan(
                [{"role": "system", "content": "fixed instructions"},
                 {"role": "user", "content": "private-user-content"}],
                [{"type": "function", "function": {"name": "compile_tex"}}],
            )
        fingerprint = collector.snapshot()
    finally:
        http_client.close()

    validate_inference_fingerprint(fingerprint)
    assert len(sent) == len(fingerprint["calls"]) == 2
    first, second = fingerprint["calls"]
    assert first["outcome"] == "error" and first["error_type"] == "BadRequestError"
    assert second["outcome"] == "success"
    assert first["tool_schema_sha256"] and second["tool_schema_sha256"] is None
    assert first["options"]["tool_choice"] == "auto"
    assert second["options"]["tool_choice"] is None
    assert second["response_model"] == {
        "status": "REPORTED", "value": "provider-model", "reason": "",
    }
    assert second["provider_system_fingerprint"]["status"] == "REPORTED"
    assert first["response_model"]["status"] == "NOT_CHECKED"
    assert all(call["purpose"] == "planner" for call in fingerprint["calls"])
    serialized = json.dumps(fingerprint)
    assert "private-user-content" not in serialized
    assert "fixed instructions" not in serialized
    assert "test-secret-key" not in serialized
    assert current_inference_collector() is None


@pytest.mark.asyncio
async def test_generation_retry_hashes_actual_system_and_fixed_examples_without_user_data(tmp_path):
    config = api_config(tmp_path)
    model = MiniCPMModel(config)
    responses = iter([provider_response(""), provider_response(r"\iint_D f")])
    http_client = mock_provider(model, lambda request: httpx.Response(200, json=next(responses)))
    try:
        with collect_inference(build_inference_identity(config)) as collector:
            await model.generate_latex(
                "private-source-integral", "integral", force_operators=[r"\iint"],
            )
        fingerprint = collector.snapshot()
    finally:
        http_client.close()

    first, second = fingerprint["calls"]
    assert first["purpose"] == second["purpose"] == "nl_generation"
    assert first["fixed_few_shot_sha256"] == second["fixed_few_shot_sha256"]
    assert first["fixed_few_shot_sha256"]
    assert first["system_prompt_sha256"] != second["system_prompt_sha256"]
    assert first["options"]["max_tokens"] == 768
    assert first["options"]["enable_thinking"] is False
    assert "private-source-integral" not in json.dumps(fingerprint)


@pytest.mark.asyncio
async def test_remaining_call_timeout_is_separate_from_stable_identity(tmp_path):
    model = MiniCPMModel(api_config(tmp_path))
    identity = build_inference_identity(model.config)
    http_client = mock_provider(
        model, lambda request: httpx.Response(200, json=provider_response()),
    )
    snapshots = []
    try:
        for timeout in (11.0, 42.0):
            with collect_inference(identity) as collector:
                await asyncio.to_thread(
                    model._completion_create, model=model.model,
                    messages=[{"role": "user", "content": "private-input"}], timeout=timeout,
                )
            snapshots.append(collector.snapshot())
    finally:
        http_client.close()
    assert snapshots[0]["identity_sha256"] == snapshots[1]["identity_sha256"]
    assert snapshots[0]["calls"][0]["effective_timeout_seconds"] == 11.0
    assert snapshots[1]["calls"][0]["effective_timeout_seconds"] == 42.0


@pytest.mark.asyncio
async def test_vision_and_completion_attempts_capture_effective_options_without_image_data(
    tmp_path,
):
    model = MiniCPMModel(api_config(tmp_path))
    http_client = mock_provider(model, lambda request: httpx.Response(
        200, json=provider_response(fingerprint=None),
    ))
    try:
        with collect_inference(build_inference_identity(model.config)) as collector:
            await model.ocr_latex(b"private-image-bytes")
            await model.complete_latex("x+\\unknown")
        fingerprint = collector.snapshot()
    finally:
        http_client.close()
    vision, completion = fingerprint["calls"]
    assert vision["purpose"] == "ocr" and vision["options"]["max_tokens"] == 512
    assert completion["purpose"] == "completion" and completion["options"]["max_tokens"] == 768
    assert vision["options"]["temperature"] == completion["options"]["temperature"] == 0.05
    assert vision["requested_model"] == completion["requested_model"] == "MiniCPM-V-4.7-1B"
    assert vision["provider_system_fingerprint"]["status"] == "NOT_CHECKED"
    assert "private-image-bytes" not in json.dumps(fingerprint)
    assert "data:image" not in json.dumps(fingerprint)


@pytest.mark.parametrize("provider_failure", ["timeout", "policy"])
def test_actual_failed_provider_attempt_survives_api_run_logging(
    tmp_path, monkeypatch, provider_failure,
):
    def handler(request):
        if provider_failure == "timeout":
            raise httpx.ReadTimeout("private provider diagnostic", request=request)
        return httpx.Response(400, json={"error": {
            "message": "private provider diagnostic", "code": "content_policy_violation",
        }})

    sdk_client = OpenAI(
        base_url="https://api.example.test/v1", api_key="test-secret-key", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    async def ready(self):
        return True

    monkeypatch.setattr(BackendManager, "ensure_ready", ready)
    monkeypatch.setattr(MiniCPMModel, "client", property(lambda self: sdk_client))
    client = TestClient(create_app(api_config(tmp_path)), raise_server_exceptions=False)
    try:
        response = client.post("/api/agent", json={"text": "unrecognized mathematical request"})
        assert response.status_code == (200 if provider_failure == "timeout" else 500)
        runs = client.get("/api/runs").json()
        assert len(runs) == 1
        fingerprint = runs[0]["inference_fingerprint"]
    finally:
        sdk_client.close()
    assert len(fingerprint["calls"]) == 1
    attempt = fingerprint["calls"][0]
    assert attempt["outcome"] == "error"
    assert attempt["error_type"] == (
        "APITimeoutError" if provider_failure == "timeout" else "BadRequestError"
    )
    assert attempt["response_model"]["status"] == "NOT_CHECKED"
    assert "private provider diagnostic" not in json.dumps(fingerprint)
    assert "test-secret-key" not in json.dumps(fingerprint)


@pytest.mark.asyncio
async def test_same_model_concurrent_requests_and_thread_context_keep_attempts_isolated(tmp_path):
    model = MiniCPMModel(api_config(tmp_path))
    barrier = threading.Barrier(2)

    def handler(request):
        content = json.loads(request.content)["messages"][-1]["content"]
        barrier.wait(timeout=5)
        return httpx.Response(200, json=provider_response(model=f"reported-{content}"))

    http_client = mock_provider(model, handler)

    async def run(label):
        with collect_inference(build_inference_identity(model.config)) as collector:
            await model.generate_latex(label, "generic")
        return collector.snapshot()

    try:
        first, second = await asyncio.gather(run("first"), run("second"))
    finally:
        http_client.close()

    assert len(first["calls"]) == len(second["calls"]) == 1
    assert first["calls"][0]["response_model"]["value"] == "reported-first"
    assert second["calls"][0]["response_model"]["value"] == "reported-second"
    assert first["identity_sha256"] == second["identity_sha256"]
    assert current_inference_collector() is None


_LOG_PATHS = [
    (path, failure) for path in ("convert", "agent", "ocr", "complete")
    for failure in (None, RuntimeError("controlled failure"), ValueError("unexpected failure"))
] + [("validate", None), ("ocr_upload", None)]


@pytest.mark.parametrize(("path", "failure"), _LOG_PATHS)
def test_all_fourteen_run_log_construction_paths_receive_fingerprints(
    tmp_path, monkeypatch, path, failure,
):
    async def result_or_fail(self, *args, **kwargs):
        assert current_inference_collector() is not None
        if failure is not None:
            raise failure
        rendered = RenderEngine(self.config).render("x")
        if path == "convert":
            return ConvertResult("x", rendered, True, Source.MODEL, "generic", 1.0, 0.0)
        return AgentRunResult("x", True, rendered, {}, committed=True)

    async def candidate(self, *args, **kwargs):
        return "x", 0

    monkeypatch.setattr(InputRouter, "process_text", result_or_fail)
    monkeypatch.setattr(InputRouter, "create_ocr_candidate", candidate)
    monkeypatch.setattr(InputRouter, "create_completion_candidate", candidate)
    monkeypatch.setattr(TeXadaAgentRuntime, "run", result_or_fail)
    monkeypatch.setattr(TeXadaAgentRuntime, "run_candidate", result_or_fail)
    client = TestClient(create_app(api_config(tmp_path)), raise_server_exceptions=False)
    if path in {"ocr", "ocr_upload"}:
        mime = "image/png" if path == "ocr" else "application/octet-stream"
        response = client.post("/api/ocr", files={"image": ("formula.png", b"image", mime)})
    elif path == "validate":
        response = client.post("/api/validate", json={"latex": "x"})
    else:
        response = client.post(f"/api/{path}", json={"text": "x"})
    expected_status = (
        415 if path == "ocr_upload" else 503 if isinstance(failure, RuntimeError)
        else 500 if failure is not None else 200
    )
    assert response.status_code == expected_status
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    fingerprint = runs[0]["inference_fingerprint"]
    assert fingerprint["status"] == "RECORDED"
    assert fingerprint["identity_sha256"]
    assert fingerprint["calls"] == []  # Mocked pipelines did not call a provider.
    assert validate_inference_fingerprint(fingerprint) == fingerprint
    detail = client.get(f"/api/runs/{runs[0]['run_id']}").json()
    assert detail["inference_fingerprint"] == fingerprint


def test_real_zero_model_agent_and_validator_have_no_provider_calls(tmp_path):
    client = TestClient(create_app(api_config(tmp_path)))
    assert client.post("/api/agent", json={"text": "求k从1到n的k平方"}).status_code == 200
    assert client.post("/api/validate", json={"latex": "x^2"}).status_code == 200
    assert {entry["operation"] for entry in client.get("/api/runs").json()} == {"agent", "validate"}
    for entry in client.get("/api/runs").json():
        assert entry["inference_fingerprint"]["calls"] == []


@pytest.mark.asyncio
async def test_settings_update_during_inference_keeps_original_request_objects(
    tmp_path, monkeypatch,
):
    started, finish = asyncio.Event(), asyncio.Event()

    async def paused_run(self, *args, **kwargs):
        if self.config.active_model_name == "old-model":
            started.set()
            await finish.wait()
        http_client = mock_provider(self.model, lambda request: httpx.Response(
            200, json=provider_response(model=json.loads(request.content)["model"]),
        ))
        try:
            await self.model.plan([{"role": "system", "content": "fixed instructions"}], [])
        finally:
            http_client.close()
        return AgentRunResult("x", True, RenderEngine(self.config).render("x"), {})

    monkeypatch.setattr(TeXadaAgentRuntime, "run", paused_run)
    app = create_app(api_config(tmp_path, openai_model_name="old-model"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test",
    ) as client:
        pending = asyncio.create_task(client.post("/api/agent", json={"text": "old request"}))
        await asyncio.wait_for(started.wait(), timeout=5)
        update = await client.post("/api/settings/backend", json={
            "backend": "openai_compatible", "openai_model_name": "new-model",
            "openai_base_url": "https://api.example.test/v1", "openai_api_key": "new-secret",
        })
        assert update.status_code == 200
        finish.set()
        assert (await pending).status_code == 200
        assert (await client.post("/api/agent", json={"text": "new request"})).status_code == 200
        runs = (await client.get("/api/runs")).json()
    by_input = {entry["input_text"]: entry for entry in runs}
    for label, expected_model in (("old request", "old-model"), ("new request", "new-model")):
        assert by_input[label]["model_name"] == expected_model
        assert by_input[label]["inference_fingerprint"]["identity"]["configured_models"] == {
            "text": expected_model, "vision": expected_model,
        }
        assert by_input[label]["inference_fingerprint"]["calls"][0]["requested_model"] == (
            expected_model
        )


def test_api_export_import_preserves_new_fingerprint_and_old_backups_stay_legacy(tmp_path):
    client = TestClient(create_app(api_config(tmp_path)))
    assert client.post("/api/validate", json={"latex": "x"}).status_code == 200
    exported = client.get("/api/runs/export").json()["run_logs"]
    saved_fingerprint = exported[0]["inference_fingerprint"]
    client.delete("/api/runs")
    assert client.post("/api/runs/import", json={"run_logs": exported}).status_code == 200
    assert client.get("/api/runs").json()[0]["inference_fingerprint"] == saved_fingerprint
    legacy_import = client.post("/api/runs/import", json={"run_logs": [{"run_id": "legacy"}]})
    assert legacy_import.status_code == 200
    assert client.get("/api/runs/legacy").json()["inference_fingerprint"] == (
        legacy_inference_fingerprint()
    )
    invalid = copy.deepcopy(exported)
    invalid[0]["run_id"] = "malicious"
    invalid[0]["inference_fingerprint"]["api_key"] = "do-not-store"
    assert client.post("/api/runs/import", json={"run_logs": invalid}).status_code == 422
    assert client.get("/api/runs/malicious").status_code == 404


def test_ui_update_does_not_relabel_the_still_bound_inference_model(tmp_path, monkeypatch):
    async def bound_run(self, *args, **kwargs):
        assert self.model.model == "bound-model"
        return AgentRunResult("x", True, RenderEngine(self.config).render("x"), {})

    monkeypatch.setattr(TeXadaAgentRuntime, "run", bound_run)
    client = TestClient(create_app(api_config(tmp_path, openai_model_name="bound-model")))
    # UI saves replace the app config but do not rebuild router/model/runtime.
    assert client.post("/api/settings/ui", json={"ui_language": "en"}).status_code == 200
    assert client.post("/api/agent", json={"text": "x"}).status_code == 200
    entry = client.get("/api/runs").json()[0]
    assert entry["model_name"] == "bound-model"
    assert entry["inference_fingerprint"]["identity"]["configured_models"]["text"] == "bound-model"
    assert entry["inference_fingerprint"]["identity"]["backend"] == "openai_compatible"


@pytest.mark.parametrize("proxy_root", ["", "/proxy"])
def test_mounted_app_and_proxy_root_path_collect_route_relative_runs(tmp_path, proxy_root):
    parent = FastAPI(root_path=proxy_root)
    parent.mount("/math", create_app(api_config(tmp_path)))
    client = TestClient(parent, root_path=proxy_root)
    prefix = f"{proxy_root}/math"

    agent = client.post(f"{prefix}/api/agent", json={"text": "求k从1到n的k平方"})
    assert agent.status_code == 200
    assert client.post(f"{prefix}/api/validate", json={"latex": "x"}).status_code == 200
    runs = client.get(f"{prefix}/api/runs").json()

    assert {entry["operation"] for entry in runs} == {"agent", "validate"}
    for entry in runs:
        assert entry["inference_fingerprint"]["status"] == "RECORDED"
        assert entry["inference_fingerprint"]["calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", [
    {"type": "function", "function": {"name": "compile_tex"}},
    {"type": "custom", "custom": {"name": "compile_tex"}},
    {"type": "allowed_tools", "allowed_tools": {
        "mode": "required", "tools": [{"type": "function", "function": {"name": "compile_tex"}}],
    }},
])
@pytest.mark.parametrize("timeout", [
    7.5, None, httpx.Timeout(7), httpx.Timeout(None),
    httpx.Timeout(connect=1, read=2, write=3, pool=4),
])
async def test_sdk_union_parameters_work_with_and_without_collection(tmp_path, choice, timeout):
    model = MiniCPMModel(api_config(tmp_path))
    observed = []

    def handler(request):
        observed.append((json.loads(request.content), request.extensions["timeout"]))
        return httpx.Response(200, json=provider_response())

    http_client = mock_provider(model, handler)
    kwargs = {
        "model": model.model, "messages": [{"role": "user", "content": "private input"}],
        "tool_choice": choice, "timeout": timeout,
    }
    try:
        without = await asyncio.to_thread(model._completion_create, **kwargs)
        with collect_inference(build_inference_identity(model.config)) as collector:
            collected = await asyncio.to_thread(model._completion_create, **kwargs)
        fingerprint = collector.snapshot()
    finally:
        http_client.close()

    assert without.choices[0].message.content == collected.choices[0].message.content == "x"
    assert observed[0] == observed[1]
    assert observed[1][0]["tool_choice"] == choice
    assert fingerprint["capture_status"] == "COMPLETE"
    assert fingerprint["capture_errors"] == []
    attempt = fingerprint["calls"][0]
    normalized = attempt["options"]["tool_choice"]
    assert normalized["type"] == choice["type"]
    if choice["type"] == "allowed_tools":
        assert normalized["mode"] == "required"
        assert normalized["tools_sha256"] == canonical_sha256(choice["allowed_tools"]["tools"])
    else:
        assert normalized["name"] == "compile_tex"
    assert attempt["effective_timeout"] == observed[1][1]
    values = list(observed[1][1].values())
    assert attempt["effective_timeout_seconds"] == (values[0] if len(set(values)) == 1 else None)
    assert validate_inference_fingerprint(fingerprint) == fingerprint
    assert "private input" not in json.dumps(fingerprint)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["begin_call", "finish_call"])
@pytest.mark.parametrize("provider_fails", [False, True])
async def test_collection_failure_preserves_sdk_result_or_error_and_marks_partial(
    tmp_path, monkeypatch, stage, provider_fails,
):
    model = MiniCPMModel(api_config(tmp_path))

    def handler(request):
        return httpx.Response(500, json={"error": {"message": "provider failure"}}) if (
            provider_fails
        ) else httpx.Response(200, json=provider_response())

    def fail_capture(*args, **kwargs):
        raise RuntimeError("private capture diagnostic with secret-user-content")

    http_client = mock_provider(model, handler)
    kwargs = {"model": model.model, "messages": [{"role": "user", "content": "private input"}]}
    try:
        with collect_inference(build_inference_identity(model.config)) as collector:
            monkeypatch.setattr(collector, stage, fail_capture)
            if provider_fails:
                with pytest.raises(InternalServerError, match="provider failure"):
                    await asyncio.to_thread(model._completion_create, **kwargs)
            else:
                response = await asyncio.to_thread(model._completion_create, **kwargs)
                assert response.choices[0].message.content == "x"
        fingerprint = collector.snapshot()
    finally:
        http_client.close()

    assert fingerprint["status"] == "RECORDED"
    assert fingerprint["capture_status"] == "PARTIAL"
    assert fingerprint["capture_errors"] == [{"stage": stage, "error_type": "RuntimeError"}]
    if stage == "begin_call":
        assert fingerprint["calls"] == []
    else:
        assert fingerprint["calls"][0]["outcome"] == ("error" if provider_fails else "success")
        assert fingerprint["calls"][0]["error_type"] == (
            "InternalServerError" if provider_fails else None
        )
        assert fingerprint["calls"][0]["response_model"]["reason"] == (
            "provider response metadata capture failed"
        )
    assert "private capture diagnostic" not in json.dumps(fingerprint)
    assert "secret-user-content" not in json.dumps(fingerprint)
    assert validate_inference_fingerprint(fingerprint) == fingerprint
