"""Semantic-unit parsing and structural diff tests."""
from texada.semantic import SemanticDiffer, SemanticParser
from texada.semantic.katex import KaTeXASTParser


def test_parser_recognizes_core_math_units():
    document = SemanticParser().parse(
        r"\frac{x_i}{\sqrt{y}}+\int_{0}^{1} f(x)\,dx"
    )

    fraction = document.root.children[0]
    integral = next(unit for unit in document.root.children if unit.kind == "integral")

    assert fraction.kind == "fraction"
    assert [child.role for child in fraction.children] == ["numerator", "denominator"]
    assert fraction.children[0].children[0].kind == "script"
    assert fraction.children[1].children[0].kind == "root"
    assert integral.value == "int"
    assert [child.role for child in integral.children] == ["lower_bound", "upper_bound"]
    assert document.diagnostics == []
    assert document.parser_backend == "katex-0.17.0-v8"


def test_parser_maps_katex_matrix_ast_to_semantic_rows_and_cells():
    document = SemanticParser().parse(
        r"\begin{pmatrix}a&b\\c&d\end{pmatrix}"
    )

    matrix = document.root.children[0]
    assert matrix.kind == "environment"
    assert matrix.value == "matrix"
    assert len(matrix.children) == 2
    assert [child.role for child in matrix.children[0].children] == [
        "column_0",
        "column_1",
    ]


def test_parser_preserves_unknown_commands_as_units():
    document = SemanticParser().parse(r"\futuremath{x}")

    command = document.root.children[0]
    assert command.kind == "command"
    assert command.value == "futuremath"


def test_semantic_diff_reports_denominator_not_character_offset():
    result = SemanticDiffer().diff(r"\frac{a}{b}", r"\frac{a}{c}")

    assert not result.equivalent
    assert result.changes[0].operation == "update"
    assert "denominator" in result.changes[0].path
    assert result.changes[0].before == "b"
    assert result.changes[0].after == "c"


def test_semantic_diff_marks_fraction_insertion_as_structural():
    result = SemanticDiffer().diff("x", r"\frac{x}{y}")
    payload = result.to_dict()

    assert payload["structural_change_count"] == 1
    assert payload["changes"][0]["unit_kind"] == "fraction"
    assert payload["weighted_cost"] > 0
    assert 0 <= payload["reward"] < 1


def test_semantic_diff_ignores_presentation_spacing_and_prunes_equal_subtrees():
    result = SemanticDiffer().diff("x + y", r"x\,+y")

    assert result.equivalent
    assert result.weighted_cost == 0
    assert result.semantic_similarity == 1


def test_katex_context_can_close_and_reopen_cleanly():
    parser = KaTeXASTParser()

    assert parser.parse("x+1").ok
    parser.close()
    assert parser.parse(r"\frac{a}{b}").ok
    parser.close()
