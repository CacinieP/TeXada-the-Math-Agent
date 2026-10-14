"""Full reference coverage and conservative equivalence-assistance boundaries."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from formula_equivalence import assist, notation_match, symbolic_evidence

from texada.semantic.katex import shared_katex_parser

ROOT = Path(__file__).resolve().parents[1]


def registry():
    return yaml.safe_load((ROOT / "eval/structure_references.yaml").read_text())


def test_all_100_references_have_complete_provenance_and_parse():
    data = registry()
    entries = data["entries"]
    assert {e["case_id"] for e in entries} == {f"{i:03d}" for i in range(1, 101)}
    assert len(entries) == 100
    for entry in entries:
        assert entry["meaning_review"] and entry["domain_assumptions"]
        assert entry["scope"] == "full_expression"
        for reference in entry["references"]:
            assert reference["review_status"] == "agent-mathematical-reviewed"
            parsed = shared_katex_parser().parse(reference["latex"])
            assert parsed.ok, (entry["case_id"], reference, parsed.error)


def test_clarified_inputs_preserve_original_text_and_dataset_identity():
    source = (ROOT / "eval/golden_set.yaml").read_bytes()
    original = {str(e["id"]).zfill(3): e for e in yaml.safe_load(source)["entries"]}
    clarified = yaml.safe_load((ROOT / "eval/full_formula_golden.yaml").read_text())
    assert clarified["source_golden_sha256"] == hashlib.sha256(source).hexdigest()
    assert len(clarified["entries"]) == 100
    for entry in clarified["entries"]:
        assert entry["original_input"] == original[entry["id"]]["input"]
    assert sum(e["input"] != e["original_input"] for e in clarified["entries"]) == 17


def test_equivalence_is_not_just_the_old_anchor():
    entries = {e["case_id"]: e for e in registry()["entries"]}
    assert assist(r"\sqrt{x}", entries["021"])["status"] == "WHOLE_NOTATION_MATCH"
    assert assist("x+y+z", entries["001"])["status"] != "WHOLE_NOTATION_MATCH"
    assert assist(r"\frac{d^n f}{dx}", entries["053"])["status"] != "WHOLE_NOTATION_MATCH"
    assert assist("x^2-1", entries["010"])["status"] != "WHOLE_NOTATION_MATCH"


def test_notation_aliases_do_not_erase_integral_measure_or_vector_rank():
    assert notation_match(r"\int_D f(x,y) dx dy", r"\iint_D f(x,y) dx dy", "065")
    assert not notation_match(r"\int_D f(x,y) dx", r"\iint_D f(x,y) dx dy", "065")
    assert notation_match(r"\vec F\cdot\vec n", r"\mathbf F\cdot\mathbf n", "080")
    assert not notation_match(r"\vec F", r"\mathbf F\cdot\mathbf n", "080")


def test_font_aliases_do_not_collapse_fields_or_imaginary_constants():
    assert not notation_match(r"\mathbb R", "R", "098")
    assert not notation_match(r"\mathrm i", "i", "001")
    assert not notation_match(r"\mathcal F", "F", "057")


def test_symbolic_assistance_is_exact_but_never_a_domain_or_intent_verdict():
    result = symbolic_evidence("a^2+2ab+b^2", "(a+b)^2", timeout=8)
    assert result["status"] == "SAME_ON_COMMON_DOMAIN", result
    assert result["domain_verified"] is False
    entries = {e["case_id"]: e for e in registry()["entries"]}
    assert assist("a^2+2ab+b^2", entries["005"])["final_verdict"] is False
    result = symbolic_evidence("x+y+z", "x+y", timeout=8)
    assert result["status"] == "NOT_PROVED", result


async def test_custom_dataset_identity_and_input_are_bound_to_actual_bytes(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import run_minicpm_v47 as runner

    monkeypatch.setenv("TEXADA_OPENAI_API_KEY", "inert-test-placeholder")
    monkeypatch.setattr(runner.BackendManager, "ensure_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(runner, "MiniCPMModel", lambda _: SimpleNamespace(
        _client=None, _completion_create=lambda **_: None,
    ))
    model_run = AsyncMock(return_value=SimpleNamespace(
        latex="x+y", valid=True, render=SimpleNamespace(katex_html="render"),
        committed=True, revision=1, stop_reason="test", tokens_used=0, trace=[],
    ))
    monkeypatch.setattr(runner, "TeXadaAgentRuntime", lambda *_a, **_kw:
                        SimpleNamespace(run=model_run))

    def wrong_source():
        raise AssertionError("original loader must not replace explicitly selected inputs")

    monkeypatch.setattr(runner, "load_golden_set", wrong_source)
    dataset = tmp_path / "custom.yaml"
    dataset.write_text(yaml.safe_dump({
        "version": "audited-inputs-test-v1", "entries": [
            {"id": "001", "input": "actual selected input", "anchor": "x+y"},
        ],
    }))
    await runner.run(SimpleNamespace(
        dataset=dataset, output_dir=tmp_path / "evidence", planner_control=False,
        limit=0, request_interval=0, structure_references=None,
    ))
    import json

    report = json.loads((tmp_path / "evidence/live-golden.json").read_text())
    assert model_run.call_args.args == ("actual selected input",)
    identity = report["inference_identity"]["dataset"]
    assert identity["version"]["value"] == "audited-inputs-test-v1"
    assert identity["sha256"]["value"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
