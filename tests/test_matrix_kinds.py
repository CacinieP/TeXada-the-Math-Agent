"""Additional matrix presets preserve their exact structural constraints."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from texada.core.matrices import MatrixSpec, check_matrix, generate_matrix, recognize_matrix
from texada.core.validator import LaTeXValidator

KINDS = ["identity", "zero", "diagonal", "upper_triangular", "lower_triangular"]


def matrix_cells(latex: str) -> list[list[str]]:
    body = latex.split("\n", 1)[1].rsplit("\n", 1)[0]
    return [[cell.strip() for cell in row.split(" & ")]
            for row in body.split(" \\\\\n")]


@pytest.mark.parametrize("rows,columns", [(1, 1), (2, 3), (3, 2), (10, 10), (20, 20)])
def test_zero_presets_expand_every_requested_cell(rows, columns):
    spec = MatrixSpec(kind="zero", rows=rows, columns=columns)
    latex = generate_matrix(spec)
    assert matrix_cells(latex) == [["0"] * columns for _ in range(rows)]
    assert LaTeXValidator().validate(latex).valid
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("size", [1, 2, 10, 20])
@pytest.mark.parametrize("start", [0, 1])
def test_identity_presets_have_only_unit_diagonal_entries(size, start):
    spec = MatrixSpec(kind="identity", rows=size, columns=size, index_start=start)
    latex = generate_matrix(spec)
    assert matrix_cells(latex) == [
        ["1" if row == column else "0" for column in range(size)] for row in range(size)
    ]
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("size", [1, 2, 10, 20])
@pytest.mark.parametrize("start", [0, 1])
@pytest.mark.parametrize("expression,template", [
    ("a_i", "a_{{{index}}}"), (r"\alpha_i", r"\alpha_{{{index}}}"),
    ("-2.5", "-2.5"), ("b", "b"),
])
def test_diagonal_presets_keep_custom_entries_and_off_diagonal_zeros(size, start,
                                                                   expression, template):
    spec = MatrixSpec(kind="diagonal", rows=size, columns=size,
                      diagonal=expression, index_start=start)
    latex = generate_matrix(spec)
    assert matrix_cells(latex) == [
        [template.format(index=start + row) if row == column else "0"
         for column in range(size)] for row in range(size)
    ]
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("kind", ["upper_triangular", "lower_triangular"])
@pytest.mark.parametrize("size", [1, 2, 10, 20])
@pytest.mark.parametrize("start", [0, 1])
@pytest.mark.parametrize("element", ["a", r"\alpha"])
def test_triangular_presets_preserve_all_retained_elements(kind, size, start, element):
    spec = MatrixSpec(kind=kind, rows=size, columns=size, element=element, index_start=start)
    latex = generate_matrix(spec)
    cells = matrix_cells(latex)
    assert len(cells) == size
    assert all(len(row) == size for row in cells)
    for row, values in enumerate(cells):
        for column, actual in enumerate(values):
            retained = row <= column if kind == "upper_triangular" else row >= column
            expected = f"{element}_{{{start + row},{start + column}}}" if retained else "0"
            assert actual == expected
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("kind", ["identity", "diagonal", "upper_triangular", "lower_triangular"])
@pytest.mark.parametrize("rows,columns", [(2, 3), ("m", "n"), (2, "n")])
def test_square_presets_reject_unequal_concrete_or_symbolic_dimensions(kind, rows, columns):
    with pytest.raises(ValidationError, match="matching row and column dimensions"):
        MatrixSpec(kind=kind, rows=rows, columns=columns)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("size", [1, 2, 5])
def test_small_compact_presets_use_the_full_display_contract(kind, size):
    spec = MatrixSpec(kind=kind, rows=size, columns=size, display="compact")
    expanded = spec.model_copy(update={"display": "expanded"})
    assert generate_matrix(spec) == generate_matrix(expanded)
    assert len(matrix_cells(generate_matrix(spec))) == size
    assert r"\times" not in generate_matrix(spec)


@pytest.mark.parametrize("kind,expected", [
    ("identity", [
        ["1", "0", "0", "0", "0"],
        ["0", "1", "0", "0", "0"],
        ["0", "0", r"\ddots", "0", "0"],
        ["0", "0", "0", "1", "0"],
        ["0", "0", "0", "0", "1"],
    ]),
    ("zero", [
        ["0", "0", r"\cdots", "0", "0"],
        ["0", "0", r"\cdots", "0", "0"],
        [r"\vdots", r"\vdots", r"\ddots", r"\vdots", r"\vdots"],
        ["0", "0", r"\cdots", "0", "0"],
        ["0", "0", r"\cdots", "0", "0"],
    ]),
    ("diagonal", [
        ["a_{1}", "0", "0", "0", "0"],
        ["0", "a_{2}", "0", "0", "0"],
        ["0", "0", r"\ddots", "0", "0"],
        ["0", "0", "0", "a_{n-1}", "0"],
        ["0", "0", "0", "0", "a_{n}"],
    ]),
    ("upper_triangular", [
        ["a_{1,1}", "a_{1,2}", r"\cdots", "a_{1,n-1}", "a_{1,n}"],
        ["0", "a_{2,2}", r"\cdots", "a_{2,n-1}", "a_{2,n}"],
        ["0", "0", r"\ddots", r"\vdots", r"\vdots"],
        ["0", "0", "0", "a_{n-1,n-1}", "a_{n-1,n}"],
        ["0", "0", "0", "0", "a_{n,n}"],
    ]),
    ("lower_triangular", [
        ["a_{1,1}", "0", "0", "0", "0"],
        ["a_{2,1}", "a_{2,2}", "0", "0", "0"],
        [r"\vdots", r"\vdots", r"\ddots", "0", "0"],
        ["a_{n-1,1}", "a_{n-1,2}", r"\cdots", "a_{n-1,n-1}", "0"],
        ["a_{n,1}", "a_{n,2}", r"\cdots", "a_{n,n-1}", "a_{n,n}"],
    ]),
])
@pytest.mark.parametrize("bracket", ["matrix", "pmatrix", "bmatrix", "vmatrix"])
def test_symbolic_presets_have_explicit_structural_schematics(kind, expected, bracket):
    spec = MatrixSpec(kind=kind, rows="n", columns="n", bracket=bracket)
    latex = generate_matrix(spec)
    assert spec.display == "compact"
    assert matrix_cells(latex) == expected
    assert latex.endswith(f"\\end{{{bracket}}}_{{n\\times n}}")
    assert LaTeXValidator().validate(latex).valid
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("kind", ["diagonal", "upper_triangular", "lower_triangular"])
@pytest.mark.parametrize("dimension,start,last,penultimate", [
    (10, 1, "10", "9"), (10, 0, "9", "8"),
    ("n", 1, "n", "n-1"), ("n", 0, "n-1", "n-2"),
])
def test_compact_endpoint_indices_follow_the_selected_origin(kind, dimension, start,
                                                            last, penultimate):
    spec = MatrixSpec(kind=kind, rows=dimension, columns=dimension,
                      display="compact", index_start=start)
    latex = generate_matrix(spec)
    cells = matrix_cells(latex)
    if kind == "diagonal":
        assert cells[0][0] == f"a_{{{start}}}"
        assert cells[-2][-2] == f"a_{{{penultimate}}}"
        assert cells[-1][-1] == f"a_{{{last}}}"
    else:
        assert cells[0][0] == f"a_{{{start},{start}}}"
        assert cells[-2][-2] == f"a_{{{penultimate},{penultimate}}}"
        assert cells[-1][-1] == f"a_{{{last},{last}}}"
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("rows,columns,expected", [
    (2, "n", [["0", "0", r"\cdots", "0", "0"]] * 2),
    ("m", 2, [["0", "0"], ["0", "0"], [r"\vdots", r"\vdots"],
              ["0", "0"], ["0", "0"]]),
])
def test_zero_presets_keep_mixed_rectangular_dimensions(rows, columns, expected):
    spec = MatrixSpec(kind="zero", rows=rows, columns=columns)
    latex = generate_matrix(spec)
    assert matrix_cells(latex) == expected
    assert latex.endswith(f"_{{{rows}\\times {columns}}}")
    assert check_matrix(spec, latex)["verdict"] == "MATCH"


@pytest.mark.parametrize("kind,candidate", [
    ("identity", r"\begin{pmatrix}2&0\\0&1\end{pmatrix}"),
    ("identity", r"\begin{pmatrix}1&1\\0&1\end{pmatrix}"),
    ("zero", r"\begin{pmatrix}0&1\\0&0\end{pmatrix}"),
    ("diagonal", r"\begin{pmatrix}a_1&1\\0&a_2\end{pmatrix}"),
    ("diagonal", r"\begin{pmatrix}a_1&0\\0&a_3\end{pmatrix}"),
    ("upper_triangular", r"\begin{pmatrix}a_{1,1}&a_{1,2}\\1&a_{2,2}\end{pmatrix}"),
    ("upper_triangular", r"\begin{pmatrix}a_{1,1}&a_{1,3}\\0&a_{2,2}\end{pmatrix}"),
    ("lower_triangular", r"\begin{pmatrix}a_{1,1}&1\\a_{2,1}&a_{2,2}\end{pmatrix}"),
    ("lower_triangular", r"\begin{pmatrix}a_{1,1}&0\\a_{3,1}&a_{2,2}\end{pmatrix}"),
])
def test_compilable_type_violations_report_the_actual_candidate_difference(kind, candidate):
    spec = MatrixSpec(kind=kind, rows=2, columns=2)
    assert LaTeXValidator().validate(candidate).valid
    result = check_matrix(spec, candidate)
    assert result["verdict"] == "DIFFERENT"
    assert result["first_difference"]
    assert result["diagnostics"]


@pytest.mark.parametrize("kind,opposite", [
    ("upper_triangular", "lower_triangular"), ("lower_triangular", "upper_triangular"),
])
def test_triangular_direction_is_checked_for_full_and_symbolic_displays(kind, opposite):
    for dimension in (3, "n"):
        spec = MatrixSpec(kind=kind, rows=dimension, columns=dimension)
        candidate = generate_matrix(spec.model_copy(update={"kind": opposite}))
        assert check_matrix(spec, candidate)["verdict"] == "DIFFERENT"


@pytest.mark.parametrize("kind", KINDS)
def test_compact_dimensions_are_required_even_for_constant_entries(kind):
    spec = MatrixSpec(kind=kind, rows=10, columns=10, display="compact", diagonal="1")
    latex = generate_matrix(spec)
    twenty = spec.model_copy(update={"rows": 20, "columns": 20})
    assert check_matrix(twenty, latex)["verdict"] == "DIFFERENT"
    assert check_matrix(spec, latex.removesuffix(r"_{10\times 10}"))["verdict"] == "DIFFERENT"


@pytest.mark.parametrize("kind,checks", [
    ("identity", {"unit_diagonal", "off_diagonal_zeros"}),
    ("zero", {"all_entries_zero"}),
    ("diagonal", {"diagonal_expressions", "off_diagonal_zeros", "element_indices"}),
    ("upper_triangular", {"upper_triangle_elements", "lower_triangle_zeros", "element_indices"}),
    ("lower_triangular", {"lower_triangle_elements", "upper_triangle_zeros", "element_indices"}),
])
def test_constraint_coverage_names_the_type_specific_regions(kind, checks):
    spec = MatrixSpec(kind=kind, rows=2, columns=2)
    coverage = check_matrix(spec, generate_matrix(spec))["coverage"]
    assert checks.issubset(coverage["checks"])
    if kind in {"identity", "zero"}:
        assert "element_indices" not in coverage["checks"]


@pytest.mark.parametrize("description", [
    "写一个10阶单位矩阵", "n阶对角矩阵", "写一个2行3列零矩阵",
    "n阶上三角矩阵", "n阶下三角矩阵",
])
def test_new_preset_types_do_not_expand_the_natural_language_grammar(description):
    assert recognize_matrix(description) is None
