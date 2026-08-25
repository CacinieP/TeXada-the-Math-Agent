"""Formula Runtime revision, evidence, and commit invariants."""

import pytest

from texada.runtime import CommitBarrierError, FormulaState, StaleRevisionError


def test_formula_state_builds_an_append_only_revision_chain():
    state = FormulaState("x", origin="input")

    unchanged = state.revise(
        "x",
        expected_revision=1,
        origin="planner",
    )
    changed = state.revise(
        "x+1",
        expected_revision=1,
        origin="planner",
    )

    assert unchanged.number == 1
    assert changed.number == 2
    assert changed.parent == 1
    assert state.latex == "x+1"
    assert [item.latex for item in state.ledger.revisions] == ["x", "x+1"]


def test_formula_state_rejects_stale_mutations():
    state = FormulaState("x")
    state.revise("x+1", expected_revision=1, origin="planner")

    with pytest.raises(StaleRevisionError, match="current revision is 2"):
        state.revise("x+2", expected_revision=1, origin="late_tool")

    assert state.latex == "x+1"
    assert state.revision == 2


def test_evidence_is_bound_to_a_revision_and_copied_on_write():
    state = FormulaState("x")
    output = {"valid": True, "diagnostics": []}

    state.add_evidence(
        revision=1,
        kind="compile_tex",
        ok=True,
        output=output,
    )
    output["valid"] = False

    stored = state.ledger.evidence[0]
    assert stored.revision == 1
    assert stored.output["valid"] is True
    stored.output["valid"] = False
    assert state.to_dict()["evidence"][0]["revision"] == 1
    assert state.to_dict()["evidence"][0]["output"]["valid"] is True


def test_commit_barrier_requires_compile_and_render_for_current_revision():
    state = FormulaState("x")
    state.add_evidence(
        revision=1,
        kind="compile_tex",
        ok=True,
        output={"valid": True},
    )
    state.add_evidence(
        revision=1,
        kind="render_math",
        ok=True,
    )
    state.revise("x+1", expected_revision=1, origin="planner")

    with pytest.raises(CommitBarrierError, match="compile evidence"):
        state.commit(expected_revision=2)

    state.add_evidence(
        revision=2,
        kind="compile_tex",
        ok=True,
        output={"valid": True},
    )
    with pytest.raises(CommitBarrierError, match="render evidence"):
        state.commit(expected_revision=2)

    state.add_evidence(
        revision=2,
        kind="render_math",
        ok=True,
    )
    commit = state.commit(expected_revision=2)

    assert commit.revision == 2
    assert state.committed is True
    assert state.to_dict()["commits"][0]["revision"] == 2
    assert state.commit(expected_revision=2) == commit
    assert len(state.ledger.commits) == 1


def test_commit_barrier_rejects_a_stale_expected_revision():
    state = FormulaState("x")
    state.revise("x+1", expected_revision=1, origin="planner")

    with pytest.raises(StaleRevisionError, match="current revision is 2"):
        state.commit(expected_revision=1)


def test_formula_evidence_rejects_an_unknown_revision():
    state = FormulaState("x")

    with pytest.raises(ValueError, match="unknown formula revision"):
        state.add_evidence(
            revision=2,
            kind="compile_tex",
            ok=True,
            output={"valid": True},
        )

    with pytest.raises(ValueError, match="unknown formula revision"):
        state.latex_at(0)


def test_planner_projection_is_compact_and_revision_scoped():
    state = FormulaState("x")
    state.add_evidence(
        revision=1,
        kind="compile_tex",
        ok=True,
        output={"valid": True, "semantic_document": {"large": "tree"}},
    )

    projection = state.planner_projection()

    assert projection == {
        "revision": 1,
        "latex": "x",
        "committed": False,
        "evidence": [{"kind": "compile_tex", "ok": True, "sequence": 1}],
    }
