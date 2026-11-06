"""Matrix generation contracts and actual candidate structure checks."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from texada.core.matrices import MatrixSpec, check_matrix, generate_matrix, recognize_matrix
from texada.semantic.katex import shared_katex_parser


def matrix_cells(latex: str) -> list[list[str]]:
    body = latex.split("\n", 1)[1].rsplit("\n", 1)[0]
    return [[cell.strip() for cell in row.split(" & ")]
            for row in body.split(" \\\\\n")]


@pytest.mark.parametrize("size", [1, 2, 10, 20])
@pytest.mark.parametrize("start", [0, 1])
def test_tridiagonal_full_expansion_checks_individual_entries(size, start):
    spec = MatrixSpec(kind="tridiagonal", rows=size, columns=size, index_start=start)
    latex = generate_matrix(spec)
    rows = matrix_cells(latex)
    assert len(rows) == size
    assert all(len(row) == size for row in rows)
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if column_index == row_index:
                assert value == f"a_{{{start + row_index}}}"
            elif column_index == row_index + 1:
                assert value == f"b_{{{start + row_index}}}"
            elif row_index == column_index + 1:
                assert value == f"c_{{{start + column_index}}}"
            else:
                assert value == "0"
    assert shared_katex_parser().parse(latex).ok


def test_rectangular_generation_keeps_multi_digit_indices_separated():
    spec = MatrixSpec(rows=10, columns=12, bracket="bmatrix")
    rows = matrix_cells(generate_matrix(spec))
    assert len(rows) == 10
    assert all(len(row) == 12 for row in rows)
    assert rows[0][0] == "a_{1,1}"
    assert rows[-1][-1] == "a_{10,12}"


@pytest.mark.parametrize("size", [1, 2, 5])
def test_small_compact_matrices_expand_without_ellipsis(size):
    spec = MatrixSpec(kind="tridiagonal", rows=size, columns=size, display="compact")
    latex = generate_matrix(spec)
    assert len(matrix_cells(latex)) == size
    assert r"\dots" not in latex
    assert r"\ddots" not in latex
    assert r"\times" not in latex


@pytest.mark.parametrize("start,last,penultimate", [(1, "n", "n-1"), (0, "n-1", "n-2")])
def test_symbolic_tridiagonal_contract_and_endpoint_indices(start, last, penultimate):
    spec = MatrixSpec(kind="tridiagonal", rows="n", columns="n", index_start=start)
    assert spec.display == "compact"
    latex = generate_matrix(spec)
    rows = matrix_cells(latex)
    assert len(rows) == 5
    assert all(len(row) == 5 for row in rows)
    assert rows[0] == [f"a_{{{start}}}", f"b_{{{start}}}", "0", r"\cdots", "0"]
    assert rows[-1] == ["0", r"\cdots", "0", f"c_{{{penultimate}}}", f"a_{{{last}}}"]
    assert rows[-2][-2:] == [f"a_{{{penultimate}}}", f"b_{{{penultimate}}}"]
    assert latex.endswith(r"\end{pmatrix}_{n\times n}")
    assert shared_katex_parser().parse(latex).ok


def test_concrete_compact_tridiagonal_uses_concrete_endpoints():
    spec = MatrixSpec(kind="tridiagonal", rows=10, columns=10, display="compact")
    rows = matrix_cells(generate_matrix(spec))
    assert rows[-2][-3:] == ["c_{8}", "a_{9}", "b_{9}"]
    assert rows[-1][-2:] == ["c_{9}", "a_{10}"]
    assert generate_matrix(spec).endswith(r"\end{pmatrix}_{10\times 10}")


def test_rectangular_symbolic_and_mixed_dimensions_keep_their_own_endpoints():
    symbolic = matrix_cells(generate_matrix(MatrixSpec(rows="m", columns="n")))
    assert symbolic[0][0] == "a_{1,1}"
    assert symbolic[-1][-1] == "a_{m,n}"
    assert symbolic[2][2] == r"\ddots"
    mixed = matrix_cells(generate_matrix(MatrixSpec(rows=2, columns="n")))
    assert len(mixed) == 2
    assert mixed[-1][-1] == "a_{2,n}"
    assert generate_matrix(MatrixSpec(rows=2, columns="n")).endswith(
        r"\end{pmatrix}_{2\times n}"
    )


def test_compact_constant_entries_require_the_actual_logical_dimension_annotation():
    ten = MatrixSpec(kind="tridiagonal", rows=10, columns=10, display="compact",
                     diagonal="a", upper="b", lower="c")
    twenty = MatrixSpec(kind="tridiagonal", rows=20, columns=20, display="compact",
                        diagonal="a", upper="b", lower="c")
    candidate = generate_matrix(ten)
    assert candidate != generate_matrix(twenty)
    assert check_matrix(ten, candidate)["verdict"] == "MATCH"
    assert check_matrix(twenty, candidate)["verdict"] == "DIFFERENT"
    unannotated = candidate.removesuffix(r"_{10\times 10}")
    assert check_matrix(ten, unannotated)["verdict"] == "DIFFERENT"


@pytest.mark.parametrize("bracket", ["matrix", "pmatrix", "bmatrix", "vmatrix"])
def test_compact_dimension_annotation_is_supported_for_each_bracket(bracket):
    spec = MatrixSpec(rows="m", columns="n", bracket=bracket)
    assert generate_matrix(spec).endswith(r"_{m\times n}")
    assert check_matrix(spec, generate_matrix(spec))["verdict"] == "MATCH"


def test_custom_expressions_are_normalized_and_used_in_the_named_directions():
    spec = MatrixSpec(kind="tridiagonal", rows=3, columns=3,
                      diagonal=r"\alpha_{i}", upper="ci", lower="-2")
    assert spec.diagonal == r"\alpha_i"
    assert spec.upper == "c_i"
    rows = matrix_cells(generate_matrix(spec))
    assert rows == [[r"\alpha_{1}", "c_{1}", "0"],
                    ["-2", r"\alpha_{2}", "c_{2}"],
                    ["0", "-2", r"\alpha_{3}"]]


@pytest.mark.parametrize("field,value", [
    ("rows", 0), ("rows", -1), ("rows", 21), ("columns", 21),
    ("rows", True), ("columns", 2.0), ("rows", "3"), ("rows", "n+1"),
    ("rows", "nn"), ("rows", " n"), ("rows", None),
    ("index_start", True), ("index_start", "1"), ("index_start", 2),
    ("element", "ab"), ("element", r"\unknown"), ("element", "a_i"),
    ("diagonal", "a_{i+1}"), ("upper", r"b_i\\1"),
    ("lower", r"\input{file}"), ("diagonal", "a_i & b_i"),
    ("bracket", "cases"), ("display", "arbitrary"),
])
def test_parameters_reject_unsupported_or_coerced_values(field, value):
    with pytest.raises(ValidationError):
        MatrixSpec(**{field: value})


def test_tridiagonal_requires_square_shape_and_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        MatrixSpec(kind="tridiagonal", rows=3, columns=4)
    with pytest.raises(ValidationError):
        MatrixSpec(kind="tridiagonal", rows="m", columns="n")
    with pytest.raises(ValidationError):
        MatrixSpec(unrecognized="value")


@pytest.mark.parametrize("description,order", [
    ("写一个矩阵，主对角线是ai，两条次对角线分别是bi，ci", "n"),
    ("写一个10阶矩阵，主对角线是ai，两条次对角线分别是bi，ci", 10),
    ("写一个十阶矩阵，主对角线是a_i，两条次对角线分别是b_i，c_i", 10),
    ("n阶三对角矩阵", "n"),
    ("生成一个二阶三对角矩阵。", 2),
])
def test_recognizer_covers_source_requests_and_explicit_tridiagonal_orders(description, order):
    spec = recognize_matrix(description)
    assert spec is not None
    assert spec.kind == "tridiagonal"
    assert spec.rows == spec.columns == order
    assert (spec.diagonal, spec.upper, spec.lower) == ("a_i", "b_i", "c_i")


def test_recognizer_respects_explicit_directions_in_either_clause_order():
    spec = recognize_matrix("写一个10阶矩阵，主对角线为ai，下对角线为bi，上对角线为ci")
    assert spec is not None
    assert (spec.upper, spec.lower) == ("c_i", "b_i")
    assert matrix_cells(generate_matrix(spec))[0][1] == "c_{1}"
    assert matrix_cells(generate_matrix(spec))[1][0] == "b_{1}"


@pytest.mark.parametrize("description,rows,columns", [
    ("通用3行4列矩阵", 3, 4),
    ("写一个3行4列矩阵", 3, 4),
    ("生成一个m行n列矩阵", "m", "n"),
    ("写一个10阶矩阵", 10, 10),
])
def test_recognizer_covers_explicit_general_shapes(description, rows, columns):
    spec = recognize_matrix(description)
    assert spec is not None
    assert spec.kind == "general"
    assert (spec.rows, spec.columns) == (rows, columns)


@pytest.mark.parametrize("description", [
    ".5阶矩阵", ".5行4列矩阵", ".5阶三对角矩阵",
    "写一个0.5阶矩阵", "通用3行.5列矩阵",
    "-5阶矩阵", "-.5阶矩阵", "写一个-0.5阶矩阵",
])
def test_recognizer_preserves_fractional_and_negative_dimension_text(description):
    assert recognize_matrix(description) is None


@pytest.mark.parametrize("punctuation", ["。", ".", "!", "！", "?", "？", "。!？"])
def test_recognizer_cleans_trailing_sentence_punctuation(punctuation):
    spec = recognize_matrix(f" 5阶矩阵{punctuation} ")
    assert spec is not None
    assert spec.rows == spec.columns == 5


@pytest.mark.parametrize("description", [
    "写一个矩阵", "写一个矩阵并求逆", "n阶三对角矩阵的逆",
    "写一个10阶矩阵，主对角线是ai，两条次对角线分别是bi，ci，其他元素为1",
    "写一个10阶矩阵，主对角线是ai，上对角线是bi",
    "写一个10阶矩阵，主对角线是ai，上对角线是bi，上对角线是ci",
    "写一个21阶三对角矩阵", "写一个零阶三对角矩阵",
    "对称矩阵", "矩阵A的逆矩阵", "矩阵A的转置",
    "写一个10阶矩阵，主对角线是ai，两条次对角线分别是bi，ci并计算特征值",
])
def test_recognizer_rejects_partial_ambiguous_or_uncovered_descriptions(description):
    assert recognize_matrix(description) is None


@pytest.mark.parametrize("spec", [
    MatrixSpec(rows=2, columns=4),
    MatrixSpec(rows="m", columns="n", bracket="bmatrix"),
    MatrixSpec(kind="tridiagonal", rows=1, columns=1),
    MatrixSpec(kind="tridiagonal", rows=2, columns=2),
    MatrixSpec(kind="tridiagonal", rows=10, columns=10),
    MatrixSpec(kind="tridiagonal", rows="n", columns="n"),
])
def test_checker_proves_supported_display_structure(spec):
    result = check_matrix(spec, generate_matrix(spec))
    assert result["verdict"] == "MATCH"
    assert result["candidate_tree_sha256"] == result["expected_tree_sha256"]
    assert result["coverage"]["logical_rows"] == spec.rows
    assert result["spec"] == spec.model_dump()


@pytest.mark.parametrize("candidate", [
    r"\begin{pmatrix}a_1&c_1&0\\b_1&a_2&c_2\\0&b_2&a_3\end{pmatrix}",
    r"\begin{pmatrix}a_1&b_1&7\\c_1&a_2&b_2\\0&c_2&a_3\end{pmatrix}",
    r"\begin{pmatrix}a_1&b_1\\c_1&a_2\end{pmatrix}",
    r"\begin{pmatrix}a_1&b_1&0\\c_1&a_2&b_2\\0&c_3&a_3\end{pmatrix}",
    r"\begin{pmatrix}a_{11}&a_{12}&\cdots\\a_{21}&a_{22}&\cdots\end{pmatrix}",
])
def test_checker_rejects_wrong_directions_band_entries_sizes_and_indices(candidate):
    spec = MatrixSpec(kind="tridiagonal", rows=3, columns=3)
    result = check_matrix(spec, candidate)
    assert result["verdict"] == "DIFFERENT"
    assert result["first_difference"]
    assert result["diagnostics"]


def test_checker_allows_transparent_subscript_braces():
    spec = MatrixSpec(kind="tridiagonal", rows=2, columns=2)
    candidate = r"\begin{pmatrix}a_1&b_1\\c_1&a_2\end{pmatrix}"
    assert check_matrix(spec, candidate)["verdict"] == "MATCH"


@pytest.mark.parametrize("candidate", [r"\futuremath{x}", r"\phantom{x}", r"\def\x{a}\x"])
def test_checker_preserves_unsupported_structure_diagnostics(candidate):
    result = check_matrix(MatrixSpec(), candidate)
    assert result["verdict"] == "UNSUPPORTED"
    assert result["diagnostics"]


def test_checker_reports_missing_candidate_without_claiming_a_match():
    assert check_matrix(MatrixSpec(), "")["verdict"] == "NOT_CHECKED"


@pytest.mark.parametrize("candidate", [
    r"\rule{0pt}{15pt}",
    r"\begin{pmatrix}a_1&\rule{0pt}{15pt}\\0&a_2\end{pmatrix}",
    r"\begin{pmatrix}a_1&\varvdots\rule{0pt}{14pt}\\0&a_2\end{pmatrix}",
])
def test_checker_keeps_arbitrary_or_altered_rules_unsupported(candidate):
    assert check_matrix(MatrixSpec(), candidate)["verdict"] == "UNSUPPORTED"


@pytest.mark.parametrize("mutation", [
    "height", "width", "shift", "mode", "extra", "symbol", "boolean_width",
])
def test_vdots_adapter_requires_the_complete_pinned_expansion(monkeypatch, mutation):
    parser = shared_katex_parser()
    original_parse = parser.parse
    original_dots = original_parse(r"\vdots")
    altered = copy.deepcopy(original_dots.ast[0])
    rule = altered["body"][1]
    if mutation == "height":
        rule["height"]["number"] = 14
    elif mutation == "width":
        rule["width"]["number"] = 1
    elif mutation == "shift":
        rule["shift"] = {"number": 1, "unit": "pt"}
    elif mutation == "mode":
        rule["mode"] = "text"
    elif mutation == "boolean_width":
        rule["width"]["number"] = False
    elif mutation == "symbol":
        altered["body"][0]["text"] = "x"
    else:
        rule["extra"] = "unrecognized"

    def parse(latex):
        if latex == "altered-dots":
            return replace(original_dots, ast=[altered])
        return original_parse(latex)

    monkeypatch.setattr(parser, "parse", parse)
    spec = MatrixSpec(kind="tridiagonal", rows="n", columns="n")
    assert check_matrix(spec, "altered-dots")["verdict"] == "UNSUPPORTED"
