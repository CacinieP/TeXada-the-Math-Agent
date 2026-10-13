"""Full-expression evaluation contracts; no inference service is required."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import run_minicpm_v47 as live_runner
import structural_match as matcher
import yaml
from anchor_match import anchor_present

ROOT = Path(__file__).resolve().parents[1]
CORPUS = yaml.safe_load((ROOT / "eval/structural_adversarial_cases.yaml").read_text())


@pytest.mark.parametrize("case", CORPUS["entries"], ids=lambda case: case["id"])
def test_authored_adversarial_pairs(case):
    result = matcher.compare_structure(case["candidate_latex"], case["reference_latex"])
    assert result.status == case["expected_status"], result.to_dict()
    assert CORPUS["reference_source"] == "synthetic_author_reference"
    assert CORPUS["review_status"] == "agent-reviewed"
    if result.status == "MATCH":
        assert result.candidate_tree_sha256 == result.reference_tree_sha256
    elif result.status == "DIFFERENT":
        assert result.first_difference
        assert result.candidate_tree_sha256 != result.reference_tree_sha256


def test_corpus_has_twenty_distinct_cases_and_full_references():
    entries = CORPUS["entries"]
    assert len(entries) == len({case["id"] for case in entries}) == 20
    assert all(case["reference_latex"] and case["reason"] for case in entries)


def test_containment_and_whole_expression_match_measure_different_contracts():
    assert anchor_present("x+y+z", "x+y")
    assert matcher.compare_structure("x+y+z", "x+y").status == "DIFFERENT"
    assert anchor_present(r"\frac{a+c}{b}", r"\frac{a}{b}")
    result = matcher.compare_structure(r"\frac{a+c}{b}", r"\frac{a}{b}")
    assert result.status == "DIFFERENT"
    assert "numerator" in result.first_difference


def test_transparent_argument_braces_and_known_symbol_aliases_match():
    assert matcher.compare_structure(r"\frac{{a}}{{b}}", r"\frac{a}{b}").status == "MATCH"
    assert matcher.compare_structure(r"x\leq1", r"x\le1").status == "MATCH"


@pytest.mark.parametrize("candidate", [
    r"\text{x+y}", r"\smash{x}+y", r"\raisebox{1pt}{$x$}+y",
    r"\futuremath{x}", r"\placeholder{}", r"\def\foo{x}\foo+y", "x 加上 y",
])
def test_unrepresented_text_wrappers_macros_and_holes_never_match(candidate):
    assert matcher.compare_structure(candidate, "x+y").status == "UNSUPPORTED"


def test_fonts_and_vector_accents_remain_structural():
    assert matcher.compare_structure(r"\mathbf{x}", "x").status == "DIFFERENT"
    assert matcher.compare_structure(r"\vec{x}", "x").status == "DIFFERENT"


@pytest.mark.parametrize("candidate", [
    r"\begin{array}{c|c}a&b\end{array}",
    r"\begin{matrix}a&b\\\hline c&d\end{matrix}",
    r"\frac{a}{", "(" + "x", "{" * 101 + "x" + "}" * 101,
])
def test_partitions_invalid_syntax_and_resource_guards_are_unsupported(candidate):
    assert matcher.compare_structure(candidate, "x").status == "UNSUPPORTED"


@pytest.mark.parametrize("depth", [100, 101, 510])
@pytest.mark.parametrize("same_expression", [False, True])
def test_ordinary_parentheses_obey_the_canonical_nesting_budget(depth, same_expression):
    reference = "(" * depth + "x" + ")" * depth
    candidate = "(" * depth + ("x" if same_expression else "y") + ")" * depth
    result = matcher.compare_structure(candidate, reference)
    if depth > matcher.MAX_NESTING_DEPTH:
        assert result.status == "UNSUPPORTED"
        assert result.reason == "reference:canonical_depth_limit"
        assert result.candidate_tree_sha256 is None
        assert result.reference_tree_sha256 is None
    else:
        assert result.status == ("MATCH" if same_expression else "DIFFERENT")
        if not same_expression:
            assert result.first_difference


@pytest.mark.parametrize("depth", [101, 510])
def test_deep_candidate_with_shallow_reference_is_unsupported(depth):
    candidate = "(" * depth + "x" + ")" * depth
    result = matcher.compare_structure(candidate, "x")
    assert result.status == "UNSUPPORTED"
    assert result.reason == "candidate:canonical_depth_limit"


def test_parentheses_and_nested_ast_nodes_share_one_depth_budget():
    inner = "(" * 55 + "x" + ")" * 55
    latex = "(" * 55 + rf"\frac{{{inner}}}{{y}}" + ")" * 55
    result = matcher.compare_structure(latex, latex)
    assert result.status == "UNSUPPORTED"
    assert result.reason == "reference:canonical_depth_limit"


@pytest.mark.parametrize("stage", ["_difference", "_hash"])
@pytest.mark.parametrize("error", [MemoryError, RecursionError])
def test_comparison_and_hash_resource_errors_are_unsupported(monkeypatch, stage, error):
    def resource_failure(*_args, **_kwargs):
        raise error("private detail")

    monkeypatch.setattr(matcher, stage, resource_failure)
    result = matcher.compare_structure("x", "x")
    assert result.status == "UNSUPPORTED"
    assert result.reason == "comparison_resource_limit"
    assert result.candidate_tree_sha256 is None
    assert result.reference_tree_sha256 is None
    assert "private" not in json.dumps(result.to_dict())


def test_parser_error_or_unknown_raw_fields_cannot_make_identical_trees_pass(monkeypatch):
    parser = SimpleNamespace(parse=lambda _: SimpleNamespace(
        ok=True, version="0.17.0",
        ast=[{"type": "mathord", "mode": "math", "text": "x", "newSemanticField": 1}],
    ))
    monkeypatch.setattr(matcher, "shared_katex_parser", lambda: parser)
    result = matcher.compare_structure("x", "x")
    assert result.status == "UNSUPPORTED"
    assert "unsupported_katex_fields" in result.reason
    parser.parse = lambda _: (_ for _ in ()).throw(RuntimeError("private detail"))
    result = matcher.compare_structure("x", "x")
    assert result.status == "UNSUPPORTED"
    assert "private" not in json.dumps(result.to_dict())


def test_missing_full_reference_is_not_checked_and_has_no_implicit_nl_reference():
    assert matcher.compare_structure("x+y", "").status == "NOT_CHECKED"
    assert matcher.check_references("x+y", []).status == "NOT_CHECKED"
    assert matcher.load_references(None) == {}


@pytest.mark.parametrize("latex", [r"\frac{a}{}", r"{}^2", r"\sqrt{}", r"\,"])
def test_equal_incomplete_structures_do_not_pass_as_full_references(latex):
    assert matcher.compare_structure(latex, latex).status == "UNSUPPORTED"


def _reference(latex, reference_id="authored-test"):
    return {"latex": latex, "reference_id": reference_id,
            "reference_source": "synthetic_author_reference", "review_status": "agent-reviewed"}


def test_reference_alternatives_are_explicit_and_unsupported_ones_remain_visible():
    references = [_reference("xy+z", "implicit"), _reference(r"x\cdot y+z", "explicit")]
    result = matcher.check_references(r"x\cdot y+z", references)
    assert result.status == "MATCH"
    assert result.reference_id == "explicit"
    result = matcher.check_references("x+y", [_reference("x-y"), _reference(r"\unknown{x}")])
    assert result.status == "UNSUPPORTED"
    assert matcher.check_references(None, references).status == "NOT_CHECKED"


def test_authored_registry_requires_scope_provenance_and_unique_ids(tmp_path):
    references = matcher.load_references(ROOT / "eval/structure_references.yaml")
    assert len(references) == 8
    assert all(reference["review_status"] == "agent-reviewed"
               for variants in references.values() for reference in variants)
    path = tmp_path / "references.yaml"
    entry = {"case_id": "001", "scope": "partial_anchor", "references": [_reference("x+y")]}
    path.write_text(yaml.safe_dump({"schema_version": 1, "entries": [entry]}))
    with pytest.raises(ValueError, match="full_expression"):
        matcher.load_references(path)
    entry["scope"] = "full_expression"
    path.write_text(yaml.safe_dump({"schema_version": 1, "entries": [entry, entry]}))
    with pytest.raises(ValueError, match="unique"):
        matcher.load_references(path)
    del entry["references"][0]["reference_source"]
    path.write_text(yaml.safe_dump({"schema_version": 1, "entries": [entry]}))
    with pytest.raises(ValueError, match="source"):
        matcher.load_references(path)


def test_aggregate_keeps_unsupported_and_missing_references_out_of_match_claims():
    rows = [{"strict_structure": {"status": status}} for status in
            ("MATCH", "DIFFERENT", "UNSUPPORTED", "NOT_CHECKED")]
    summary = matcher.summarize_structure(rows)
    assert summary["counts"] == dict.fromkeys(
        ("MATCH", "DIFFERENT", "UNSUPPORTED", "NOT_CHECKED"), 1)
    assert summary["comparable"] == 2
    assert summary["attempted"] == 3
    assert summary["match_rate_comparable"] == 0.5
    assert summary["comparable_coverage"] == 0.5
    assert matcher.summarize_structure([])["match_rate_comparable"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("with_references", [False, True])
@pytest.mark.parametrize("inference_fails", [False, True])
async def test_live_runner_adds_independent_optional_structure_without_network(
    monkeypatch, tmp_path, with_references, inference_fails,
):
    monkeypatch.setenv("TEXADA_OPENAI_API_KEY", "inert-test-placeholder")
    monkeypatch.setattr(live_runner, "load_golden_set", lambda: [
        {"id": "001", "input": "This natural language is not an AST reference", "anchor": "x+y"},
    ])
    fake_model = SimpleNamespace(_client=None, _completion_create=lambda **_: None)
    monkeypatch.setattr(live_runner, "MiniCPMModel", lambda _: fake_model)
    result = SimpleNamespace(latex="x+y+z", valid=True,
                             render=SimpleNamespace(katex_html="rendered"), committed=True,
                             revision=1, stop_reason="test", tokens_used=0, trace=[])
    fake_run = AsyncMock(side_effect=RuntimeError("unavailable")) if inference_fails else (
        AsyncMock(return_value=result))
    monkeypatch.setattr(live_runner, "TeXadaAgentRuntime", lambda *_args, **_kwargs:
                        SimpleNamespace(run=fake_run))
    registry = tmp_path / "references.yaml"
    reference_bytes = (ROOT / "eval/structure_references.yaml").read_bytes()
    registry.write_bytes(reference_bytes)

    async def endpoint_ready(_backend):
        registry.write_text("changed after load")
        return True

    monkeypatch.setattr(live_runner.BackendManager, "ensure_ready", endpoint_ready)
    args = SimpleNamespace(output_dir=tmp_path, planner_control=False, limit=1,
                           request_interval=0,
                           structure_references=registry
                           if with_references else None)
    await live_runner.run(args)
    report = json.loads((tmp_path / "live-golden.json").read_text())
    row = report["rows"][0]
    assert row["anchor_containment"] == (not inference_fails)
    expected_status = "DIFFERENT" if with_references and not inference_fails else "NOT_CHECKED"
    assert row["strict_structure"]["status"] == expected_status
    assert bool(report["strict_structure_evaluation"]["references_sha256"]) == with_references
    if with_references:
        assert report["strict_structure_evaluation"]["references_sha256"] == (
            hashlib.sha256(reference_bytes).hexdigest())
        assert row["strict_structure"]["reference_review_status"] == "agent-reviewed"
    assert report["summary"]["anchor_containment_passed"] == int(not inference_fails)
    assert report["summary"]["strict_structure"]["counts"]["MATCH"] == 0
