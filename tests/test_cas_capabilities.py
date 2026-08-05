"""Executable contract for eval/cas_capabilities.yaml."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from texada.cas import AlgebraChecker, CASStatus
from texada.cas.policy import POLICY_VERSION, compare_expressions
from texada.semantic import SemanticParser

sp = pytest.importorskip("sympy")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "eval" / "cas_capabilities.yaml"


@pytest.fixture(scope="module")
def matrix():
    return yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))


def test_capability_matrix_locks_environment_and_schema(matrix):
    assert matrix["schema_version"] == 1
    environment = matrix["environment"]

    assert sp.__version__ == environment["sympy"]["version"]
    assert version("antlr4-python3-runtime") == environment["antlr4-python3-runtime"]["version"]
    assert version("lark") == environment["lark"]["version"]
    assert version("psutil") == environment["psutil"]["version"]
    assert environment["sympy"]["pin"] == "==1.14.0"
    assert environment["antlr4-python3-runtime"]["pin"] == "==4.11"
    assert environment["lark"]["pin"] == "==1.3.1"
    assert environment["psutil"]["pin"] == ">=6.1,<8"
    assert matrix["policy"]["version"] == POLICY_VERSION
    assert matrix["policy"]["default_seed"] == 0
    assert matrix["worker_resources"]["rss_unit"] == "bytes"
    assert matrix["worker_resources"]["default_startup_timeout_ms"] == 10_000
    assert matrix["worker_resources"]["default_max_rss_bytes"] == 512 * 1024**2
    assert matrix["worker_resources"]["platforms"]["macos"]["rlimit_as_authority"] is False
    assert matrix["cache"]["key_fields"] == [
        "fingerprint_a",
        "fingerprint_b",
        "assumptions",
        "sympy_version",
        "policy_version",
        "seed",
    ]

    for case in matrix["raw_parser_probes"]:
        assert "backend" in case
        assert "strict" in case


def test_semantic_adapter_matrix_has_zero_false_verified(matrix):
    parser = SemanticParser()
    false_verified: list[str] = []

    default_seed = matrix["policy"]["default_seed"]
    with AlgebraChecker(seed=default_seed) as checker:
        for case in matrix["semantic_adapter_cases"]:
            result = checker.check(
                parser.parse(case["lhs"]),
                parser.parse(case["rhs"]),
                assumptions=case["assumptions"],
                timeout_ms=case["timeout_ms"],
                seed=default_seed,
            )
            expected = case["expected"]
            if result.verified and expected["status"] != CASStatus.EQUIVALENT.value:
                false_verified.append(case["id"])
            assert result.status.value == expected["status"], (
                case["id"],
                result.to_dict(),
            )
            if "basis" in expected:
                assert result.basis.value == expected["basis"], (
                    case["id"],
                    result.to_dict(),
                )
            if "evidence_grade" in expected:
                assert result.evidence_grade.value == expected["evidence_grade"], (
                    case["id"],
                    result.to_dict(),
                )
            if "reason_code" in expected:
                assert result.reason_code == expected["reason_code"], (
                    case["id"],
                    result.to_dict(),
                )
            if "witness" in expected:
                assert result.witness == expected["witness"], (
                    case["id"],
                    result.to_dict(),
                )
            if result.verified:
                assert result.basis.value
                assert isinstance(result.assumptions, list)
                assert result.seed == default_seed
                assert result.policy_version == POLICY_VERSION
                assert result.sympy_version == matrix["environment"]["sympy"]["version"]
                assert result.cache_key

    assert len(false_verified) <= matrix["acceptance"]["maximum_false_verified"]


def test_raw_parser_probe_matrix_is_reproducible(matrix):
    from sympy.parsing.latex import parse_latex

    for case in matrix["raw_parser_probes"]:
        expected = case["expected"]
        try:
            expression = parse_latex(
                case["latex"],
                backend=case["backend"],
                strict=case["strict"],
            )
        except Exception as exc:
            assert expected["outcome"] == "error", (case["id"], type(exc), str(exc))
            exception_name = f"{type(exc).__module__}.{type(exc).__name__}"
            assert exception_name == expected["exception"], case["id"]
            continue

        assert expected["outcome"] == "parsed", case["id"]
        type_name = f"{type(expression).__module__}.{type(expression).__name__}"
        assert type_name == expected["type"], case["id"]
        assert sp.srepr(expression) == expected["srepr"], case["id"]


def test_sympy_equals_contract_probes(matrix):
    k = sp.Symbol("k", integer=True, positive=True)
    x = sp.Symbol("x")
    probes = {
        "harmonic_sum_false_before_doit": (
            sp.Sum(1 / k, (k, 1, sp.oo)),
            sp.oo,
        ),
        "definite_integral_true_before_doit": (
            sp.Integral(x**2, (x, 0, 1)),
            sp.Rational(1, 3),
        ),
        "finite_sum_true_before_doit": (
            sp.Sum(k, (k, 1, 5)),
            sp.Integer(15),
        ),
    }

    for case in matrix["sympy_contract_probes"]:
        if case["tier"] != "ci":
            continue
        lhs, rhs = probes[case["id"]]
        expected = case["expected"]
        assert lhs.equals(rhs) is expected["equals_before_doit"], case["id"]
        evaluated = lhs.doit()
        assert sp.srepr(evaluated) == expected["doit_srepr"], case["id"]
        assert evaluated.equals(rhs) is expected["equals_after_doit"], case["id"]
        if "policy_status" in expected:
            result = compare_expressions(lhs, rhs)
            assert result.status.value == expected["policy_status"], case["id"]
            assert result.basis.value == expected["policy_basis"], case["id"]
            assert result.reason_code == expected["policy_reason_code"], case["id"]
            assert result.observation["lhs_convergence"] == expected["convergence_observation"], (
                case["id"]
            )
            assert result.status.value not in expected["forbidden_statuses"], case["id"]


def test_sympy_random_probe_is_seeded_and_reproducible(matrix):
    from sympy.core.random import seed

    x = sp.Symbol("x")
    probes = {"sqrt_square_equals_symbol": (sp.sqrt(x**2), x)}

    for case in matrix["sympy_random_probes"]:
        lhs, rhs = probes[case["id"]]
        for selected_seed, expected in case["expected_by_seed"].items():
            observed = []
            for _ in range(case["repetitions"]):
                seed(selected_seed)
                observed.append(lhs.equals(rhs))
            assert observed == [expected] * case["repetitions"], (
                case["id"],
                selected_seed,
                observed,
            )


def test_generated_capability_document_is_current():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render-cas-capabilities.py"),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
