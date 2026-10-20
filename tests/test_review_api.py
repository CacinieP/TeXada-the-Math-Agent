"""Actual local runtime-to-review HTTP flow over the surviving review surface.

NL, OCR and completion candidates now commit directly, so the only route that
still produces a pending review is the Studio handoff transfer
(`POST /api/handoff/formula`, `requires_review: true`). Reviews that need a
synthetic source image are registered directly into the application review
store, which keeps the controlled-source-read assertions offline and exact.
"""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from texada.agent.protocol import PlannerTurn
from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.model import MiniCPMModel
from texada.core.router import InputRouter
from texada.handoff import text_digest
from texada.render.engine import RenderEngine
from texada.runtime import FormulaState
from texada.store.pending_review import input_source_hash


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    async def candidate(_self, _image):
        return r"\frac{x}{2}", 1

    async def plan(_self, _messages, _tools):
        return PlannerTurn(content=r"\frac{x}{2}")

    monkeypatch.setattr(InputRouter, "create_ocr_candidate", candidate)
    monkeypatch.setattr(MiniCPMModel, "plan", plan)
    monkeypatch.setattr(BackendManager, "ensure_ready", AsyncMock(return_value=True))
    # llama_server reports the MiniCPM-V-4.7-1B checkpoint the transfer binds to.
    app = create_app(
        TeXadaConfig(nl_candidate_first=False, backend="llama_server", data_dir=tmp_path)
    )
    yield TestClient(app)


def png_source():
    output = io.BytesIO()
    Image.new("RGB", (15, 15), "blue").save(output, format="PNG")
    return output.getvalue()


def handoff_request(original=r"\frac{x}{2", **updates):
    """A Studio transfer whose contract forbids an automatic commit."""
    request = {
        "schema_version": 1,
        "transfer_id": str(uuid4()),
        "document_sha256": text_digest("document:" + original),
        "input_sha256": text_digest(original),
        "source_range": {"start": 0, "end": len(original), "encoding": "unicode-codepoints"},
        "formula_id": "formula-1",
        "expected_revision": 7,
        "original_latex": original,
        "requested_action": "repair",
        "allowed_scope": "syntax_repair",
        "checkpoint": "MiniCPM-V-4.7-1B",
        "budget": {"max_steps": 3, "max_seconds": 90, "max_tokens": 256},
        "requires_review": True,
        "evidence": [],
    }
    request.update(updates)
    return request


def request_handoff_review(client):
    """Drive the one remaining user-facing path that creates a pending review."""
    response = client.post("/api/handoff/formula", json=handoff_request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "review_required"
    review = body["review"]
    assert review["status"] == "pending" and review["committed"] is False
    return body, review


def register_held_review(client, *, image=None, text="original source"):
    """Register a pending review straight into the application review store."""
    state = FormulaState(r"\frac{x}{2}")
    state.revise(r"\frac{x}{3}", expected_revision=1, origin="planner_final")
    state.add_evidence(
        revision=state.revision, kind="compile_tex", ok=True, output={"valid": True}
    )
    state.add_evidence(revision=state.revision, kind="render_math", ok=True)
    review = client.app.state.review_store.register(
        state,
        input_hash=input_source_hash(text, image),
        source_text=text,
        source_image=image,
        source_mime="image/png" if image else "",
        render=RenderEngine(TeXadaConfig()).render(state.latex),
        reasons=["trusted_review_required"],
    )
    assert review["status"] == "pending"
    return review


def confirmation(review, decision="accept"):
    return {
        "decision": decision,
        **{
            key: review[key]
            for key in (
                "input_hash",
                "parent_revision",
                "candidate_hash",
                "current_revision",
            )
        },
    }


def handoff_run_ids(client):
    return [
        run["run_id"]
        for run in client.get("/api/runs/export").json()["run_logs"]
        if run["operation"] == "formula_handoff"
    ]


def test_handoff_review_flow_exposes_controlled_original_and_separate_checks(review_client):
    body, review = request_handoff_review(review_client)
    assert body["candidate"] == r"\frac{x}{2}"
    assert body["candidate_sha256"] == review["candidate_hash"]
    assert review["checks"]["compile"]["status"] == "valid"
    assert review["checks"]["render"]["status"] == "rendered"
    assert review["checks"]["human"]["status"] == "pending"
    assert review["checks"]["intent"]["status"] == "not_checked"
    # Only formula text is transferred; no source image is invented for it.
    assert review["source_image_url"] is None
    assert review_client.get(f"/api/reviews/{review['id']}/source").status_code == 404
    assert review_client.get("/api/history/export").json()["history"] == []
    runs = [
        run
        for run in review_client.get("/api/runs/export").json()["run_logs"]
        if run["operation"] == "formula_handoff"
    ]
    assert len(runs) == 1
    assert review["id"] not in json.dumps(runs[0]["inference_fingerprint"])


def test_source_image_read_is_controlled_and_never_serialized(review_client):
    image = png_source()
    review = register_held_review(review_client, image=image)
    assert review["source_image_url"] == f"/api/reviews/{review['id']}/source"
    source = review_client.get(review["source_image_url"])
    assert source.status_code == 200 and source.content == image
    assert source.headers["x-content-type-options"] == "nosniff"
    assert source.headers["cache-control"] == "no-store"
    assert "source_image" not in review and "source_image_digest" not in review
    accepted = review_client.post(
        f"/api/reviews/{review['id']}/decision", json=confirmation(review)
    )
    assert accepted.status_code == 200, accepted.text
    logs = review_client.get("/api/runs/export").json()["run_logs"]
    assert base64.b64encode(image).decode() not in json.dumps(logs)


def test_accept_is_exact_revision_bound_and_only_then_adds_history(review_client):
    body, review = request_handoff_review(review_client)
    path = f"/api/reviews/{review['id']}/decision"
    accepted = review_client.post(path, json=confirmation(review))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted" and accepted.json()["committed"]
    duplicate = review_client.post(path, json=confirmation(review))
    assert duplicate.status_code == 200
    entries = review_client.get("/api/history/export").json()["history"]
    assert len(entries) == 1
    assert entries[0]["run_id"] in handoff_run_ids(review_client)
    assert entries[0]["input_text"] == body["original_latex"]
    assert entries[0]["latex"] == body["candidate"]
    opposite = review_client.post(path, json=confirmation(review, "reject"))
    assert opposite.status_code == 409


def test_nested_decision_binding_is_compatible_and_conflicting_dual_binding_is_rejected(
    review_client,
):
    _body, review = request_handoff_review(review_client)
    assert review["binding"] == {
        key: review[key]
        for key in (
            "input_hash",
            "parent_revision",
            "candidate_hash",
            "current_revision",
        )
    }
    path = f"/api/reviews/{review['id']}/decision"
    conflict = review_client.post(
        path,
        json={
            **confirmation(review),
            "binding": {**review["binding"], "candidate_hash": "0" * 64},
        },
    )
    assert conflict.status_code == 422
    accepted = review_client.post(path, json={"decision": "accept", "binding": review["binding"]})
    assert accepted.status_code == 200 and accepted.json()["committed"]


def test_reject_preserves_uncommitted_candidate_and_never_adds_history(review_client):
    _body, review = request_handoff_review(review_client)
    response = review_client.post(
        f"/api/reviews/{review['id']}/decision", json=confirmation(review, "reject")
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected" and not response.json()["committed"]
    assert review_client.get("/api/history/export").json()["history"] == []


@pytest.mark.parametrize(
    "field", ["input_hash", "candidate_hash", "parent_revision", "current_revision"]
)
def test_api_rejects_each_mismatched_binding_field(review_client, field):
    _body, review = request_handoff_review(review_client)
    payload = confirmation(review)
    payload[field] = "0" * 64 if field.endswith("hash") else 99
    response = review_client.post(f"/api/reviews/{review['id']}/decision", json=payload)
    assert response.status_code == 409
    assert not review_client.app.state.review_store.get(review["id"])["committed"]


def test_api_rechecks_server_state_and_expiry(review_client):
    _body, review = request_handoff_review(review_client)
    store = review_client.app.state.review_store
    state = store._items[review["id"]].state
    state.revise("x+1", expected_revision=state.revision, origin="late-candidate")
    response = review_client.post(
        f"/api/reviews/{review['id']}/decision", json=confirmation(review)
    )
    assert response.status_code == 409 and not state.committed
    store.clock = lambda: 1e20
    expired = review_client.post(f"/api/reviews/{review['id']}/decision", json=confirmation(review))
    assert expired.status_code == 410
    assert review_client.get(f"/api/reviews/{review['id']}/source").status_code == 410


def test_accept_still_requires_current_compile_evidence(review_client):
    _body, review = request_handoff_review(review_client)
    state = review_client.app.state.review_store._items[review["id"]].state
    state.add_evidence(
        revision=state.revision, kind="compile_tex", ok=False, output={"valid": False}
    )
    failed = review_client.post(f"/api/reviews/{review['id']}/decision", json=confirmation(review))
    assert failed.status_code == 409 and not state.committed
    assert (
        review_client.app.state.review_store.get(review["id"])["checks"]["compile"]["status"]
        == "invalid"
    )


def test_low_risk_nl_stays_automatic_and_no_source_image_review_is_invented(review_client):
    response = review_client.post("/api/agent", json={"text": "求k从1到n的k平方"})
    assert response.status_code == 200
    body = response.json()
    assert body["committed"] and body["review"] is None
    assert body["confidence"] == 0.0


def test_review_write_and_source_are_subject_to_browser_origin_guard(review_client):
    _body, review = request_handoff_review(review_client)
    headers = {"Origin": "https://untrusted.invalid"}
    denied = review_client.post(
        f"/api/reviews/{review['id']}/decision", json=confirmation(review), headers=headers
    )
    assert denied.status_code == 403
    source = review_client.get(f"/api/reviews/{review['id']}/source", headers=headers)
    assert source.status_code == 403
