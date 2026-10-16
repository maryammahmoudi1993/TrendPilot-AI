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


# --- ragged rows ---------------------------------------------------------------------


def rows(count, template="2024-01-{d:02d},{d},x\n"):
    return "".join(template.format(d=d) for d in range(1, count + 1))


def test_clean_file_reports_no_ragged_rows():
    info = sniff_csv(("date,v,s\n" + rows(5)).encode())
    assert info["ragged"] == {"count": 0, "short": 0, "long": 0, "lines": []}


def test_trailing_short_row_is_accepted_and_reported():
    info = sniff_csv(b"date,v,s\n2024-01-01,1,a\n2024-01-02,2,b\n2024-01-03,3\n")
    assert info["delimiter"] == ","
    assert info["row_count"] == 3
    assert info["ragged"] == {"count": 1, "short": 1, "long": 0, "lines": [4]}


def test_one_long_row_in_a_big_file_is_accepted_and_reported():
    text = "date,v,s\n" + rows(150) + "2024-06-01,1,a,extra\n" + rows(10)
    info = sniff_csv(text.encode())
    assert info["row_count"] == 161
    assert info["ragged"]["long"] == 1 and info["ragged"]["short"] == 0
    assert info["ragged"]["lines"] == [152]


def test_half_ragged_rows_are_rejected_with_a_clear_message():
    good, bad = "2024-01-01,1,a\n", "2024-01-02,2\n"
    with pytest.raises(CsvSniffError, match=r"5 of 10 rows.*same number of fields"):
        sniff_csv(("date,v,s\n" + (good + bad) * 5).encode())


def test_too_many_ragged_rows_name_the_first_lines():
    text = "date,v,s\n" + rows(50) + "a,b\nc,d\ne,f\n"
    with pytest.raises(CsvSniffError, match=r"first.*lines? 52, 53, 54"):
        sniff_csv(text.encode())


def test_limit_is_a_setting(settings):
    text = "date,v,s\n" + rows(50) + "a,b\nc,d\ne,f\n"
    settings.DATASET_MAX_RAGGED_SHARE = 0.1
    assert sniff_csv(text.encode())["ragged"]["count"] == 3
    settings.DATASET_MAX_RAGGED_SHARE = 0.0
    with pytest.raises(CsvSniffError):
        sniff_csv(text.encode())


def test_the_limit_is_a_share_of_rows_with_a_floor_of_one_row():
    big = "date,v,s\n" + rows(100) + "a,b\n"
    assert sniff_csv(big.encode())["ragged"]["count"] == 1  # 1 of 101 rows, within 1%
    two = "date,v,s\n" + rows(100) + "a,b\nc,d\n"
    with pytest.raises(CsvSniffError):
        sniff_csv(two.encode())  # 2 of 102 rows is above 1%


def test_blank_lines_are_not_counted_as_ragged():
    info = sniff_csv(b"date,v\n2024-01-01,1\n2024-01-02,2\n\n")
    assert info["ragged"]["count"] == 0


def test_only_the_first_ten_ragged_lines_are_listed():
    settings_text = "date,v,s\n" + rows(2000) + "a,b\n" * 12
    info = sniff_csv(settings_text.encode())
    assert info["ragged"]["count"] == 12 and len(info["ragged"]["lines"]) == 10


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_delimiter_is_still_detected_with_a_ragged_trailing_row(delimiter):
    text = delimiter.join(["date", "v", "s"]) + "\n" + rows(30).replace(",", delimiter)
    text += delimiter.join(["2024-02-01", "1"]) + "\n"
    info = sniff_csv(text.encode())
    assert info["delimiter"] == delimiter and info["ragged"]["short"] == 1


def test_commas_inside_quotes_do_not_confuse_the_delimiter():
    text = 'date;note;v\n2024-01-01;"a, b, c";1\n2024-01-02;"d, e";2\n2024-01-03;"f";3\n'
    info = sniff_csv(text.encode())
    assert info["delimiter"] == ";" and info["ragged"]["count"] == 0


def test_single_column_file_is_still_rejected():
    with pytest.raises(CsvSniffError, match="delimiter"):
        sniff_csv(b"value\n1\n2\n3\n")
