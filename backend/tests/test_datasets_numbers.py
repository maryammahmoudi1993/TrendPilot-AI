import pytest

from apps.datasets.numbers import detect_decimal_separator, parse_number, parse_numeric_column


@pytest.mark.parametrize(
    ("cell", "decimal", "expected"),
    [
        ("1234", ".", 1234.0),
        ("12.5", ".", 12.5),
        ("1,234.56", ".", 1234.56),
        ("1,234,567", ".", 1234567.0),
        ("1.234,56", ",", 1234.56),
        ("1.234.567", ",", 1234567.0),
        ("12,5", ",", 12.5),
        ("1 234,5", ",", 1234.5),
        ("1 234,5", ",", 1234.5),
        ("1'234.5", ".", 1234.5),
        ("-1,234.5", ".", -1234.5),
        ("+7", ".", 7.0),
        ("−5", ".", -5.0),
        ("1.5e3", ".", 1500.0),
        ("  42  ", ".", 42.0),
        ("0,500", ",", 0.5),
    ],
)
def test_parse_number_valid(cell, decimal, expected):
    assert parse_number(cell, decimal) == expected


@pytest.mark.parametrize(
    ("cell", "decimal"),
    [
        ("abc", "."),
        ("12abc", "."),
        ("1,23,456", "."),  # not groups of three
        ("1.234,56", "."),  # decimal comma in a dot column
        ("1.2.3", "."),
        ("$12", "."),
        ("12%", "."),
        ("inf", "."),
        ("--5", "."),
        ("1,,2", "."),
    ],
)
def test_parse_number_invalid(cell, decimal):
    assert parse_number(cell, decimal) is None


def test_detect_us_format():
    assert detect_decimal_separator(["1,234.56", "10", "2,000.5"]) == (".", False)


def test_detect_eu_format():
    assert detect_decimal_separator(["1.234,56", "10", "2.000,5"]) == (",", False)


def test_detect_decimal_comma_without_thousands():
    assert detect_decimal_separator(["12,5", "3,75"]) == (",", False)


def test_thousands_only_column_is_decisive():
    assert detect_decimal_separator(["1,234,567", "8"]) == (".", False)
    assert detect_decimal_separator(["1.234.567", "8"]) == (",", False)


def test_only_ambiguous_evidence_is_flagged():
    assert detect_decimal_separator(["1,234", "5,678", "9"]) == (".", True)


def test_hint_overrides_detection():
    assert detect_decimal_separator(["1,234", "5,678"], hint=",") == (",", False)
    result = parse_numeric_column(["1,234", "5,678"], decimal_hint=",")
    assert result.converted == 2 and not result.ambiguous
    assert parse_number("1,234", ",") == 1.234


def test_column_result_counts_and_examples():
    cells = ["1,000", "2,500.5", "", "N/A", "abc", "3", "x1", "7,5,5", "-", "y", "z", "w"]
    result = parse_numeric_column(cells)
    assert result.converted == 3
    assert result.empty == 3  # "", "N/A", "-"
    assert result.failed == 6
    assert result.failed_examples == ["abc", "x1", "7,5,5", "y", "z"]  # first five only
    assert result.decimal_separator == "."


def test_column_with_decimal_commas_and_spaces():
    result = parse_numeric_column(["1 234,5", "99,9", "0,25"])
    assert (result.decimal_separator, result.converted, result.failed) == (",", 3, 0)


def test_mixed_conventions_in_one_column_report_the_minority_as_failed():
    result = parse_numeric_column(["1,234.5", "2,345.5", "3,456.5", "1.234,5"])
    assert result.decimal_separator == "."
    assert result.converted == 3
    assert result.failed == 1
    assert result.failed_examples == ["1.234,5"]
