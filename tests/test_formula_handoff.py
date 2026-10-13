"""Actual held-state handoff, strict source bindings, and bounded SDK attempts."""
import asyncio
import copy
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from pydantic import ValidationError

from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel
from texada.handoff import (
    FormulaTransfer,
    HandoffError,
    TransferRegistry,
    bounded_configuration,
    text_digest,
)


def config(tmp_path, **updates):
    return TeXadaConfig(**{
        "data_dir": tmp_path, "backend": "openai_compatible",
        "openai_base_url": "https://api.example.test/v1",
        "openai_api_key": "inert-handoff-secret",
        "openai_model_name": "MiniCPM-V-4.7-1B",
        "openai_vision_model_name": "MiniCPM-V-4.7-1B", **updates,
    })


def envelope(original=r"\frac{x}{2", **updates):
    value = {
        "schema_version": 1, "transfer_id": str(uuid4()),
        "document_sha256": text_digest("😀$"+original+"$"),
        "input_sha256": text_digest(original),
        "source_range": {"start": 2, "end": 2+len(original), "encoding": "unicode-codepoints"},
        "formula_id": "formula-1", "expected_revision": 7, "original_latex": original,
        "requested_action": "repair", "allowed_scope": "syntax_repair",
        "checkpoint": "MiniCPM-V-4.7-1B",
        "budget": {"max_steps": 3, "max_seconds": 90, "max_tokens": 256},
        "requires_review": True, "evidence": [],
    }
    value.update(updates)
    return value


@pytest.mark.parametrize("patch", [
    {"input_sha256": "0"*64}, {"expected_revision": True}, {"requires_review": 1},
    {"requires_review": False}, {"schema_version": True}, {"checkpoint": "another-model"},
    {"allowed_scope": "completion_prefix"}, {"evidence": [{"url": "file:///private"}]},
    {"endpoint": "https://other.example"}, {"transfer_id": "not-a-uuid"},
    {"source_range": {"start": 2, "end": 3, "encoding": "unicode-codepoints"}},
    {"budget": {"max_steps": 9, "max_seconds": 90, "max_tokens": 256}},
    {"budget": {"max_steps": 3, "max_seconds": float("nan"), "max_tokens": 256}},
])
def test_untrusted_envelope_cannot_replace_source_scope_checkpoint_or_budget(patch):
    with pytest.raises(ValidationError):
        FormulaTransfer.model_validate(envelope(**patch))


def test_effective_budget_clamps_without_mutating_configuration(tmp_path):
    cfg = config(tmp_path, agent_max_steps=2, max_tokens=128, tool_timeout_seconds=4)
    transfer = FormulaTransfer.model_validate(envelope(
        budget={"max_steps": 8, "max_seconds": 2, "max_tokens": 1024},
    ))
    effective = bounded_configuration(cfg, transfer)
    assert (effective.agent_max_steps, effective.max_tokens) == (2, 128)
    assert effective.api_request_timeout_seconds == effective.inference_timeout_seconds == 2
    assert effective.tool_timeout_seconds == 2
    assert cfg.api_request_timeout_seconds == 240 and cfg.tool_timeout_seconds == 4
    with pytest.raises(HandoffError, match="CHECKPOINT_MISMATCH"):
        bounded_configuration(
            cfg.model_copy(update={"openai_vision_model_name": "different"}), transfer,
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_executes_once_cache_isolation_and_conflict():
    registry, calls = TransferRegistry(), []
    transfer = FormulaTransfer.model_validate(envelope())
    entered, release = asyncio.Event(), asyncio.Event()

    async def execute():
        calls.append(1)
        entered.set()
        await release.wait()
        return {"candidate": {"latex": "x"}}

    first = asyncio.create_task(registry.execute(transfer, execute))
    await entered.wait()
    second = asyncio.create_task(registry.execute(transfer, execute))
    conflicting = transfer.model_copy(update={"expected_revision": 8})
    with pytest.raises(HandoffError, match="TRANSFER_ID_CONFLICT"):
        await registry.execute(conflicting, execute)
    release.set()
    results = await asyncio.gather(first, second)
    assert calls == [1] and results[0] == results[1]
    results[0]["candidate"]["latex"] = "tampered"
    assert (await registry.execute(transfer, execute))["candidate"]["latex"] == "x"


@pytest.mark.asyncio
async def test_failed_and_cancelled_transfer_never_silently_reexecutes():
    registry, calls = TransferRegistry(), []
    transfer = FormulaTransfer.model_validate(envelope())

    async def fail():
        calls.append(1)
        raise RuntimeError("inert private credential must not escape")

    for _ in range(2):
        with pytest.raises(HandoffError, match="^TRANSFER_EXECUTION_FAILED$"):
            await registry.execute(transfer, fail)
    assert calls == [1]
    transfer2 = FormulaTransfer.model_validate(envelope())
    entered = asyncio.Event()

    async def hang():
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(registry.execute(transfer2, hang))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(HandoffError, match="TRANSFER_CANCELLED"):
        await registry.execute(transfer2, fail)
    assert calls == [1]


@pytest.mark.asyncio
async def test_capacity_and_completed_expiry_are_bounded():
    now = [0]
    registry = TransferRegistry(max_items=1, ttl_seconds=2, clock=lambda: now[0])
    first, second = (FormulaTransfer.model_validate(envelope()) for _ in range(2))
    async def execute():
        return {"value": 1}
    await registry.execute(first, execute)
    with pytest.raises(HandoffError, match="TRANSFER_CAPACITY"):
        await registry.execute(second, execute)
    now[0] = 3
    assert await registry.execute(second, execute) == {"value": 1}


def test_repair_http_has_real_checks_review_binding_and_no_provider_request(tmp_path, monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("deterministic repair must not call a provider")
    monkeypatch.setattr(MiniCPMModel, "plan", forbidden)
    app = create_app(config(tmp_path))
    with TestClient(app) as client:
        request = envelope()
        response = client.post("/api/handoff/formula", json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["candidate"] == r"\frac{x}{2}"
        assert body["status"] == "review_required" and body["review"]["status"] == "pending"
        assert body["review"]["checks"]["compile"]["status"] == "valid"
        assert body["parent_revision"] == 1 and body["candidate_revision"] == 2
        assert all(isinstance(body["evidence"][key], dict)
                   for key in ("mutation_scope", "cas_transition"))
        assert body["inference_fingerprint"]["status"] == "RECORDED"
        assert body["inference_fingerprint"]["calls"] == []
        assert body["review"]["transfer_context"]["effective_budget"]["max_tokens"] == 256
        assert client.get("/api/history/export").json()["history"] == []
        assert client.post("/api/handoff/formula", json=request).json() == body
        conflicting = {**request, "expected_revision": 8}
        assert client.post("/api/handoff/formula", json=conflicting).status_code == 409
        review, binding = body["review"], body["review"]["binding"]
        path = "/api/reviews/"+review["id"]+"/decision"
        wrong = {**binding, "candidate_hash": "0"*64}
        assert client.post(path, json={"decision": "accept", "binding": wrong}).status_code == 409
        accepted = client.post(path, json={"decision": "accept", "binding": binding})
        assert accepted.status_code == 200 and accepted.json()["committed"]
        assert accepted.json()["status"] == "accepted"
        assert client.post(path, json={"decision": "accept", "binding": binding}).status_code == 200
        assert len(client.get("/api/history/export").json()["history"]) == 1
        assert client.post(path, json={"decision": "reject", "binding": binding}).status_code == 409
        logs = client.get("/api/runs/export").json()["run_logs"]
        runs = [run for run in logs if run["operation"] == "formula_handoff"]
        assert len(runs) == 1
        assert runs[0]["inference_fingerprint"] == body["inference_fingerprint"]
        assert "inert-handoff-secret" not in json.dumps(body)+json.dumps(logs)


def test_unchanged_parent_null_and_reject_retains_source(tmp_path):
    with TestClient(create_app(config(tmp_path))) as client:
        body = client.post("/api/handoff/formula", json=envelope("x+1")).json()
        assert body["parent_revision"] is None
        review = body["review"]
        rejected = client.post("/api/reviews/"+review["id"]+"/decision",
                               json={"decision": "reject", "binding": review["binding"]})
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
        assert not rejected.json()["committed"]
        assert client.get("/api/history/export").json()["history"] == []


def test_completion_sdk_uses_only_formula_and_actual_bounded_identity(tmp_path, monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "fake", "object": "chat.completion", "created": 0,
            "model": "MiniCPM-V-4.7-1B",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "x+1"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        })
    def sdk(_self):
        if _self._client is None:
            _self._client = OpenAI(
                api_key="inert-handoff-secret", base_url="https://api.example.test/v1",
                max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
        return _self._client
    monkeypatch.setattr(MiniCPMModel, "client", property(sdk))
    with TestClient(create_app(config(tmp_path))) as client:
        request = envelope("x", requested_action="complete", allowed_scope="completion_prefix",
                           budget={"max_steps": 1, "max_seconds": 2, "max_tokens": 64})
        body = client.post("/api/handoff/formula", json=request)
        assert body.status_code == 200, body.text
        result = body.json()
        assert result["candidate"] == "x+1" and result["review"]["status"] == "pending"
        assert len(requests) == 1 and requests[0]["model"] == "MiniCPM-V-4.7-1B"
        assert requests[0]["max_tokens"] == 64
        assert requests[0]["messages"][-1]["content"] == "x"
        assert requests[0]["chat_template_kwargs"]["enable_thinking"] is False
        identity = result["inference_fingerprint"]["identity"]
        assert identity["configuration"]["agent_max_steps"] == 1
        assert identity["configuration"]["max_tokens"] == 64
        assert identity["configuration"]["api_request_timeout_seconds"] == 2
        calls = result["inference_fingerprint"]["calls"]
        assert len(calls) == 1 and calls[0]["purpose"] == "completion"
        assert calls[0]["requested_model"] == "MiniCPM-V-4.7-1B"
        assert "inert-handoff-secret" not in json.dumps(result)


def test_handoff_timeout_never_registers_or_commits_and_retry_is_cached(tmp_path, monkeypatch):
    calls = []
    async def delayed(_self, _partial):
        calls.append(1)
        await asyncio.sleep(10)
    monkeypatch.setattr(MiniCPMModel, "complete_latex", delayed)
    with TestClient(create_app(config(tmp_path))) as client:
        request = envelope("x+", requested_action="complete", allowed_scope="completion_prefix",
                           budget={"max_steps": 1, "max_seconds": .02, "max_tokens": 64})
        for _ in range(2):
            response = client.post("/api/handoff/formula", json=copy.deepcopy(request))
            assert response.status_code == 504 and response.json()["detail"] == "TRANSFER_TIMEOUT"
        assert calls == [1]
        assert client.get("/api/history/export").json()["history"] == []


def test_configured_checkpoint_mismatch_is_rejected_without_generation(tmp_path, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("wrong checkpoint must not execute")
    monkeypatch.setattr(MiniCPMModel, "complete_latex", forbidden)
    with TestClient(create_app(config(tmp_path, openai_model_name="different"))) as client:
        response = client.post("/api/handoff/formula", json=envelope())
        assert response.status_code == 409 and response.json()["detail"] == "CHECKPOINT_MISMATCH"
