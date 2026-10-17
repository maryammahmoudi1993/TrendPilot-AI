import pytest

from apps.datasets.columns import iter_chunks, read_columns, read_table
from apps.datasets.validation import sniff_csv
from tests.helpers import make_dataset

pytestmark = pytest.mark.django_db


@pytest.fixture
def ws(two_workspaces):
    return two_workspaces["a"]["workspace"]


def numbered(n: int) -> str:
    return "a,b\n" + "".join(f"{i},{i * 10}\n" for i in range(n))


def test_chunks_cover_every_row_in_order(ws):
    dataset = make_dataset(ws, numbered(25))
    chunks = list(iter_chunks(dataset, ["a"], chunk_rows=10))
    assert [len(c.columns["a"]) for c in chunks] == [10, 10, 5]
    assert [v for c in chunks for v in c.columns["a"]] == [str(i) for i in range(25)]


def test_chunked_and_whole_reads_agree(ws):
    dataset = make_dataset(ws, numbered(25))
    _, whole = read_columns(dataset, ["a", "b"])
    chunked = {"a": [], "b": []}
    for chunk in iter_chunks(dataset, ["a", "b"], chunk_rows=7):
        for name in chunked:
            chunked[name].extend(chunk.columns[name])
    assert chunked == whole


def test_line_numbers_follow_the_file_and_blank_lines_are_skipped(ws):
    dataset = make_dataset(ws, "a,b\n1,2\n\n3,4\n\n\n5,6\n")
    header, columns, lines = read_table(dataset, ["a"])
    assert header == ["a", "b"]
    assert columns == {"a": ["1", "3", "5"]}
    assert lines == [2, 4, 7]


def test_a_quoted_field_with_a_newline_is_one_row(ws):
    dataset = make_dataset(ws, 'a,b\n"x\ny",2\n3,4\n')
    _, columns, lines = read_table(dataset, ["a", "b"])
    assert columns == {"a": ["x\ny", "3"], "b": ["2", "4"]}
    assert lines == [3, 4]  # a row is numbered by its last physical line, as at upload


def test_short_rows_are_padded_and_long_rows_truncated(ws):
    dataset = make_dataset(ws, "a,b,c\n1,2,3\n4,5\n6,7,8,9\n")
    _, columns, _ = read_table(dataset, ["c"])
    assert columns == {"c": ["3", "", "8"]}


def test_bom_semicolons_and_unknown_names(ws):
    dataset = make_dataset(ws, "\ufeffa;b\n1;2\n")
    header, columns, _ = read_table(dataset, ["b", "zz"])
    assert header == ["a", "b"] and columns == {"b": ["2"]}


def test_upload_report_counts_blank_lines_and_row_count_excludes_them():
    info = sniff_csv(b"date,v\n2024-01-01,1\n\n2024-01-02,2\n\n\n")
    assert info["row_count"] == 2
    assert info["blank_lines"] == 3
