import pytest

from apps.datasets.validation import CsvSniffError, sniff_csv


def test_valid_comma_csv():
    info = sniff_csv(b"date,value\n2024-01-01,1\n2024-01-02,2\n")
    assert info["delimiter"] == ","
    assert info["header"] == ["date", "value"]
    assert info["row_count"] == 2


def test_semicolon_delimiter_detected():
    info = sniff_csv(b"date;value\n2024-01-01;1\n2024-01-02;2\n")
    assert info["delimiter"] == ";"
    assert info["row_count"] == 2


def test_tab_delimiter_detected():
    info = sniff_csv(b"date\tvalue\n2024-01-01\t1\n2024-01-02\t2\n")
    assert info["delimiter"] == "\t"
    assert info["row_count"] == 2


def test_utf8_bom_is_stripped_and_does_not_break_the_header():
    info = sniff_csv("﻿date,value\n2024-01-01,1\n".encode())
    assert info["header"] == ["date", "value"]


def test_binary_content_rejected():
    with pytest.raises(CsvSniffError, match="binary"):
        sniff_csv(bytes(range(256)))


def test_invalid_utf8_rejected():
    with pytest.raises(CsvSniffError, match="UTF-8"):
        sniff_csv(b"date,value\n\xff\xfe,1\n")


def test_unsupported_delimiter_rejected():
    with pytest.raises(CsvSniffError, match="delimiter"):
        sniff_csv(b"date|value\n2024-01-01|1\n2024-01-02|2\n")


def test_header_only_file_rejected_as_no_data_rows():
    with pytest.raises(CsvSniffError, match="no data rows"):
        sniff_csv(b"date,value\n")


def test_empty_bytes_rejected():
    with pytest.raises(CsvSniffError):
        sniff_csv(b"")
