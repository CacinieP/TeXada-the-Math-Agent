"""Human decisions cannot target a stale, changed or unchecked authority."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest
from PIL import Image

from texada.agent.mutation_scope import MutationScopeGuard
from texada.agent.protocol import PlannerToolCall, PlannerTurn
from texada.agent.runtime import TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.core.inference_fingerprint import build_inference_identity, collect_inference
from texada.render.engine import RenderEngine
from texada.runtime import FormulaState
from texada.store.pending_review import (
    PendingReviewStore,
    ReviewBinding,
    ReviewError,
    input_source_hash,
)


def source_png(color="blue"):
    output = io.BytesIO()
    Image.new("RGB", (12, 12), color=color).save(output, format="PNG")
    return output.getvalue()


def state_for(before=r"\frac{x}{2}", after=r"\frac{x}{3}", *, valid=True, rendered=True):
    state = FormulaState(before)
    if after != before:
        scope = MutationScopeGuard(task="ocr").assess(
            before,
            after,
            origin="planner_final",
            parent_revision=1,
            child_revision=2,
        )
        state.revise(after, expected_revision=1, origin="planner_final")
        state.add_evidence(revision=2, kind="mutation_scope", ok=False, output=scope.to_dict())
    state.add_evidence(
        revision=state.revision, kind="compile_tex", ok=valid, output={"valid": valid}
    )
    state.add_evidence(revision=state.revision, kind="render_math", ok=rendered)
    return state


def register(store, state=None, *, text="original source", image=None):
    state = state or state_for()
    return store.register(
        state,
        input_hash=input_source_hash(text, image),
        source_text=text,
        source_image=image,
        source_mime="image/png" if image else "",
        render=RenderEngine(
            TeXadaConfig(
                nl_candidate_first=False,
                nl_require_review=False,
            )
        ).render(state.latex),
        reasons=["ocr"],
    )


def binding(dto):
    return ReviewBinding(
        *(
            dto[key]
            for key in (
                "input_hash",
                "parent_revision",
                "candidate_hash",
                "current_revision",
            )
        )
    )


def test_review_holds_exact_state_and_accept_records_explicit_risk_authorization():
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state)
    assert not state.committed
    assert dto["checks"]["compile"]["status"] == "valid"
    assert dto["checks"]["human"]["status"] == "pending"
    assert dto["checks"]["intent"]["status"] == "not_checked"
    assert dto["source_image_url"] is None
    assert "denominator" in dto["role_diff"][0]["path"]
    assert dto["role_diff"][0]["position"]["status"] == "available"
    accepted = store.decide(dto["id"], decision="accept", binding=binding(dto))
    assert accepted["status"] == "accepted" and state.committed
    assert any(item.kind == "mutation_scope" and not item.ok for item in state.ledger.evidence)
    human = [item for item in state.ledger.evidence if item.kind == "human_review"][-1]
    assert human.output["scope_risk_explicitly_authorized"]
    assert not human.output["source_image_available"]
    assert human.output["intent_status"] == "NOT_CHECKED"


@pytest.mark.parametrize("prefix", [r"\,", "{a+b}"])
def test_canonical_root_changes_never_highlight_another_fraction(prefix):
    before = prefix + r"\frac{a}{b}\frac{x}{y}"
    after = prefix + r"\frac{a}{b}\frac{x}{z}"
    dto = register(PendingReviewStore(), state_for(before, after))
    denominators = [item for item in dto["role_diff"] if "denominator" in item["path"]]
    assert len(denominators) == 1
    assert denominators[0]["position"] == {
        "status": "unavailable", "source": "parent_latex", "offset_units": "utf16"
    }


def test_aligned_raw_roots_highlight_the_changed_fraction_exactly():
    before = r"12\frac{a}{b}\frac{x}{y}"
    after = r"12\frac{a}{b}\frac{x}{z}"
    dto = register(PendingReviewStore(), state_for(before, after))
    denominator = next(item for item in dto["role_diff"] if "denominator" in item["path"])
    position = denominator["position"]
    assert position["status"] == "available"
    assert before[position["start"]:position["end"]] == "{y}"


def test_registration_rejects_changed_original_source_bytes():
    store = PendingReviewStore()
    state = state_for()
    state.review_input_hash = input_source_hash("original")
    with pytest.raises(ReviewError, match="source bytes"):
        store.register(
            state,
            input_hash=input_source_hash("original"),
            source_text="changed",
            render=RenderEngine(
                TeXadaConfig(
                    nl_candidate_first=False,
                    nl_require_review=False,
                )
            ).render(state.latex),
            reasons=["risk"],
        )


def test_revision_change_during_accept_is_a_conflict_not_a_wrong_commit(monkeypatch):
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state)
    commit = state.commit

    def racing_commit(*, expected_revision):
        state.revise("z", expected_revision=state.revision, origin="racing-change")
        return commit(expected_revision=expected_revision)

    monkeypatch.setattr(state, "commit", racing_commit)
    with pytest.raises(ReviewError) as caught:
        store.decide(dto["id"], decision="accept", binding=binding(dto))
    assert caught.value.status_code == 409 and not state.committed


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_hash", "0" * 64),
        ("parent_revision", None),
        ("candidate_hash", "1" * 64),
        ("current_revision", 9),
    ],
)
def test_every_binding_component_must_match(field, value):
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state)
    fields = binding(dto).to_dict()
    fields[field] = value
    with pytest.raises(ReviewError) as caught:
        store.decide(dto["id"], decision="accept", binding=ReviewBinding(**fields))
    assert caught.value.status_code == 409 and not state.committed


@pytest.mark.parametrize(
    "change", ["revision", "input_hash", "source_text", "source_image", "source_image_removed"]
)
def test_server_rechecks_held_source_and_state(change):
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state, image=source_png())
    if change == "revision":
        state.revise("x", expected_revision=state.revision, origin="late-change")
    elif change == "input_hash":
        state.review_input_hash = "0" * 64
    elif change == "source_text":
        store._items[dto["id"]].source_text = "changed source"
    elif change == "source_image":
        store._items[dto["id"]].source_image = source_png("red")
    else:
        store._items[dto["id"]].source_image = None
    with pytest.raises(ReviewError) as caught:
        store.decide(dto["id"], decision="accept", binding=binding(dto))
    assert caught.value.status_code == 409 and not state.committed


def test_ttl_expiry_and_capacity_eviction_invalidate_confirmation():
    now = [0.0]
    store = PendingReviewStore(ttl_seconds=3, max_items=1, clock=lambda: now[0])
    first = register(store)
    second = register(store)
    with pytest.raises(ReviewError) as evicted:
        store.get(first["id"])
    assert evicted.value.status_code == 410
    now[0] = 4
    with pytest.raises(ReviewError) as expired:
        store.decide(second["id"], decision="accept", binding=binding(second))
    assert expired.value.status_code == 410 and not store._items


def test_host_abandonment_invalidates_only_pending_reviews_idempotently():
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state, image=source_png())
    assert store._source_bytes() > 0
    assert store.discard_pending(dto["id"])
    assert not store.discard_pending(dto["id"])
    assert not store.discard_pending("unknown")
    assert not state.committed and store._source_bytes() == 0
    with pytest.raises(ReviewError) as abandoned:
        store.decide(dto["id"], decision="accept", binding=binding(dto))
    assert abandoned.value.status_code == 410


@pytest.mark.parametrize("decision,status", [("accept", "accepted"), ("reject", "rejected")])
def test_host_abandonment_cannot_remove_a_human_decision(decision, status):
    store = PendingReviewStore()
    dto = register(store)
    store.decide(dto["id"], decision=decision, binding=binding(dto))
    assert not store.discard_pending(dto["id"])
    assert store.get(dto["id"])["status"] == status


def test_source_bytes_are_bounded_and_never_in_a_public_dto():
    png = source_png()
    store = PendingReviewStore(max_source_bytes=len(png))
    first = register(store, image=png)
    second = register(store, image=png)
    assert store._source_bytes() <= len(png)
    assert store.source(second["id"]) == (png, "image/png")
    assert first["id"] in store._expired
    assert "source_image" not in second and "source_image_digest" not in second
    too_small = PendingReviewStore(max_source_bytes=1)
    with pytest.raises(ReviewError) as caught:
        register(too_small, image=png)
    assert caught.value.status_code == 413


@pytest.mark.parametrize("valid,rendered", [(False, True), (True, False)])
def test_human_accept_never_overrides_compile_or_render_barrier(valid, rendered):
    store, state = PendingReviewStore(), state_for(valid=valid, rendered=rendered)
    dto = register(store, state)
    with pytest.raises(ReviewError, match="cannot accept"):
        store.decide(dto["id"], decision="accept", binding=binding(dto))
    assert not state.committed and store.get(dto["id"])["status"] == "pending"


def test_rejection_idempotence_opposite_decision_and_concurrent_retries():
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: store.decide(dto["id"], decision="reject", binding=binding(dto)),
                range(16),
            )
        )
    assert all(item["status"] == "rejected" for item in responses)
    assert len([item for item in state.ledger.evidence if item.kind == "human_review"]) == 1
    assert not state.committed
    with pytest.raises(ReviewError, match="opposite"):
        store.decide(dto["id"], decision="accept", binding=binding(dto))


def test_simultaneous_opposite_decisions_have_one_authoritative_winner():
    store, state = PendingReviewStore(), state_for()
    dto = register(store, state)

    def decide(decision):
        try:
            return store.decide(dto["id"], decision=decision, binding=binding(dto))["status"]
        except ReviewError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, ["accept", "reject"]))
    assert outcomes.count("conflict") == 1
    assert len([item for item in state.ledger.evidence if item.kind == "human_review"]) == 1


class Planner:
    def __init__(self, turns):
        self.turns = list(turns)

    async def plan(self, *_args):
        return self.turns.pop(0)

    @staticmethod
    def extract_latex(content):
        return content


@pytest.mark.asyncio
async def test_ocr_must_review_even_when_trusted_caller_requests_no_review(tmp_path):
    from unittest.mock import AsyncMock

    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path),
        model=Planner([PlannerTurn(content="x")]),
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    result = await runtime.run_candidate(
        "ocr",
        "synthetic.png",
        "x",
        requires_review=False,
        _source_image=source_png(),
        initial_tokens_used=1,
    )
    assert result.valid and not result.committed
    assert result.review_reasons == ["ocr_source_requires_review"]
    assert result._formula_state is not None
    assert "_formula_state" not in asdict(result) and "_state" not in asdict(result)


@pytest.mark.asyncio
async def test_forced_review_also_covers_deterministic_candidate_shortcut(tmp_path):
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path),
        model=Planner([]),
    )
    result = await runtime.run("求k从1到n的k平方", requires_review=True)
    assert result.valid and not result.committed
    assert result.stop_reason == "human_review_required"
    assert result.review_reasons == ["trusted_review_required"]


@pytest.mark.asyncio
async def test_low_risk_nl_preserves_auto_commit_and_cannot_claim_intent_proof(tmp_path):
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path),
        model=Planner([]),
    )
    result = await runtime.run("求k从1到n的k平方")
    assert result.committed and not result.review_reasons
    assert result.formula_ledger["evidence"][0]["output"]["intent_status"] == "NOT_CHECKED"


@pytest.mark.asyncio
async def test_nl_denominator_drift_needs_review_even_under_synthesis_grant(tmp_path):
    from unittest.mock import AsyncMock

    planner = Planner([
        PlannerTurn(tool_calls=[PlannerToolCall(
            "proposal", "propose_candidate",
            {"expected_revision": 1, "latex": r"\frac{x}{3}"},
        )]),
        PlannerTurn(content=r"\frac{x}{3}"),
    ])
    planner.generate_latex = AsyncMock(return_value=r"\frac{x}{2}")
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_require_review=False, data_dir=tmp_path, nl_candidate_first=True),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    runtime.candidate_engine.propose = lambda _text: None
    result = await runtime.run("Write half of x")
    assert result.valid and not result.committed
    assert "high_risk_role_change" in result.review_reasons
    assert result.stop_reason == "human_review_required"


def test_exact_cas_counterexample_requires_review_independently_of_scope():
    state = FormulaState("x")
    state.add_evidence(
        revision=1,
        kind="cas_transition",
        ok=False,
        output={"verdict": "different", "basis": "exact_counterexample"},
    )
    assert TeXadaAgentRuntime._review_reasons(state) == ["cas_counterexample"]


@pytest.mark.asyncio
async def test_handoff_repair_parent_does_not_apply_model_alias_normalization(tmp_path):
    original = r"\int\int f(x)dx"
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path),
        model=Planner([]),
    )
    result = await runtime.run_candidate("repair", original, original, requires_review=True)
    assert result.valid and not result.committed
    assert result.latex == original and result.revision == 1
    assert result.formula_ledger["revisions"][0]["latex"] == original
    assert result.review_reasons == ["trusted_review_required"]


@pytest.mark.asyncio
async def test_handoff_repair_has_constrained_parent_not_nl_synthesis(tmp_path):
    from unittest.mock import AsyncMock

    original = r"\frac{x}{2"
    planner = Planner([])
    planner.plan = AsyncMock(side_effect=AssertionError("host repair does not call the model"))
    runtime = TeXadaAgentRuntime(
        TeXadaConfig(nl_candidate_first=False, nl_require_review=False, data_dir=tmp_path),
        model=planner,
    )
    runtime.backend.ensure_ready = AsyncMock(return_value=True)
    identity = build_inference_identity(runtime.config, tool_schemas=runtime.tools.schemas)
    with collect_inference(identity) as collector:
        result = await runtime.run_candidate(
            "repair",
            original,
            original,
            requires_review=True,
            input_source_hash=input_source_hash(original),
        )
    assert collector.snapshot()["calls"] == []
    assert result.valid and not result.committed and result._formula_state
    scope = [
        item["output"]
        for item in result.formula_ledger["evidence"]
        if item["kind"] == "mutation_scope"
    ]
    assert scope[0]["transition"] == "preserve_structure"
    assert scope[-1]["transition"] == "syntax_repair"
    assert result._formula_state.review_input_hash == input_source_hash(original)
    planner.plan.assert_not_awaited()
    runtime.backend.ensure_ready.assert_not_awaited()
    assert [call["name"] for call in result.trace[0]["tool_calls"]] == [
        "compile_tex",
        "repair_tex",
        "compile_tex",
        "render_math",
    ]
    store = PendingReviewStore()
    review = store.register(
        result._formula_state,
        input_hash=input_source_hash(original),
        source_text=original,
        render=result.render,
        reasons=result.review_reasons,
    )
    assert review["parent_revision"] == 1 and review["current_revision"] == 2
    accepted = store.decide(review["id"], decision="accept", binding=binding(review))
    assert accepted["committed"]
    with pytest.raises(ValueError, match="exact original"):
        await runtime.run_candidate("repair", original, "y", requires_review=True)
