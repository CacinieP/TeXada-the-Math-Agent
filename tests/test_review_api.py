"""Actual local runtime-to-review HTTP flow, using public synthetic source images."""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from texada.agent.protocol import PlannerTurn
from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.backend import BackendManager
from texada.core.model import MiniCPMModel
from texada.core.router import InputRouter


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    async def candidate(_self, _image):
        return r"\frac{x}{2}", 1

    async def plan(_self, _messages, _tools):
        return PlannerTurn(content=r"\frac{x}{2}")

    monkeypatch.setattr(InputRouter, "create_ocr_candidate", candidate)
    monkeypatch.setattr(MiniCPMModel, "plan", plan)
    monkeypatch.setattr(BackendManager, "ensure_ready", AsyncMock(return_value=True))
    app = create_app(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path)
    )
    yield TestClient(app)


def png_source():
    output = io.BytesIO()
    Image.new("RGB", (15, 15), "blue").save(output, format="PNG")
    return output.getvalue()


def request_ocr(client):
    data = png_source()
    response = client.post("/api/ocr", files={"image": ("synthetic.png", data, "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] and not body["committed"]
    assert body["review"]["status"] == "pending"
    return body, data


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


def test_ocr_http_flow_exposes_controlled_original_and_separate_checks(review_client):
    body, image = request_ocr(review_client)
    review = body["review"]
    assert body["confidence"] == 0.0
    assert review["source_image_url"] == f"/api/reviews/{review['id']}/source"
    assert review["checks"]["compile"]["status"] == "valid"
    assert review["checks"]["render"]["status"] == "rendered"
    assert review["checks"]["human"]["status"] == "pending"
    assert review["checks"]["intent"]["status"] == "not_checked"
    source = review_client.get(review["source_image_url"])
    assert source.status_code == 200 and source.content == image
    assert source.headers["x-content-type-options"] == "nosniff"
    assert source.headers["cache-control"] == "no-store"
    assert review_client.get("/api/history/export").json()["history"] == []
    run = review_client.get(f"/api/runs/{body['run_id']}").json()
    serialized = json.dumps(run)
    assert base64.b64encode(image).decode() not in serialized
    assert review["source_image_url"] not in serialized
    assert review["id"] not in json.dumps(run["inference_fingerprint"])


def test_accept_is_exact_revision_bound_and_only_then_adds_history(review_client):
    body, _ = request_ocr(review_client)
    review = body["review"]
    path = f"/api/reviews/{review['id']}/decision"
    accepted = review_client.post(path, json=confirmation(review))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted" and accepted.json()["committed"]
    duplicate = review_client.post(path, json=confirmation(review))
    assert duplicate.status_code == 200
    entries = review_client.get("/api/history/export").json()["history"]
    assert len(entries) == 1 and entries[0]["run_id"] == body["run_id"]
    opposite = review_client.post(path, json=confirmation(review, "reject"))
    assert opposite.status_code == 409


def test_nested_decision_binding_is_compatible_and_conflicting_dual_binding_is_rejected(
    review_client,
):
    body, _ = request_ocr(review_client)
    review = body["review"]
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
    body, _ = request_ocr(review_client)
    review = body["review"]
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
    body, _ = request_ocr(review_client)
    review = body["review"]
    payload = confirmation(review)
    payload[field] = "0" * 64 if field.endswith("hash") else 99
    response = review_client.post(f"/api/reviews/{review['id']}/decision", json=payload)
    assert response.status_code == 409
    assert not review_client.app.state.review_store.get(review["id"])["committed"]


def test_api_rechecks_server_state_and_expiry(review_client):
    body, _ = request_ocr(review_client)
    review = body["review"]
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
    assert review_client.get(review["source_image_url"]).status_code == 410


def test_accept_still_requires_current_compile_evidence(review_client):
    body, _ = request_ocr(review_client)
    review = body["review"]
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
    body, _ = request_ocr(review_client)
    review = body["review"]
    headers = {"Origin": "https://untrusted.invalid"}
    denied = review_client.post(
        f"/api/reviews/{review['id']}/decision", json=confirmation(review), headers=headers
    )
    assert denied.status_code == 403
    assert review_client.get(review["source_image_url"], headers=headers).status_code == 403
