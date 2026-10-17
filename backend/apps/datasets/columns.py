"""Read selected columns of a stored dataset CSV as raw strings, in chunks.

Parsing uses the stdlib ``csv`` module with the dialect ``validation.detect_dialect``
chose at upload, so the mapping endpoint and the quality report see the same cells. Blank
lines are skipped, short rows are padded and long rows truncated. Every row carries the
file line number it ended on (the header is line 1), the same numbering the upload uses.
"""

import csv
import io
from dataclasses import dataclass

from django.conf import settings

from .validation import MAX_SNIFF_BYTES, detect_dialect


@dataclass
class Chunk:
    columns: dict[str, list[str]]
    lines: list[int]


def _open_text(dataset):
    return io.TextIOWrapper(dataset.file.open("rb"), encoding="utf-8-sig", newline="")


def _dialect(text_handle):
    sample = text_handle.read(MAX_SNIFF_BYTES + 1)
    text_handle.seek(0)
    return detect_dialect(sample)


def iter_chunks(dataset, names=(), chunk_rows: int | None = None, header_out: list | None = None):
    """Yield ``Chunk``s of at most ``chunk_rows`` rows holding the requested columns.

    The header is copied into ``header_out`` (a list the caller passes) once the file is
    opened; names missing from the header are skipped, callers check it first. Raises
    ``FileNotFoundError`` when the file is gone and ``ValueError`` when it cannot be
    decoded or has no usable delimiter.
    """
    chunk_rows = chunk_rows or settings.DATASET_READ_CHUNK_ROWS
    try:
        with _open_text(dataset) as handle:
            reader = csv.reader(handle, _dialect(handle))
            header = next(reader)
            if header_out is not None:
                header_out[:] = header
            wanted = {name: header.index(name) for name in names if name in header}
            columns: dict[str, list[str]] = {name: [] for name in wanted}
            lines: list[int] = []
            for row in reader:
                if not row:  # a blank line is not a data row
                    continue
                for name, idx in wanted.items():
                    columns[name].append(row[idx] if idx < len(row) else "")
                lines.append(reader.line_num)
                if len(lines) == chunk_rows:
                    yield Chunk(columns, lines)
                    columns = {name: [] for name in wanted}
                    lines = []
            if lines:
                yield Chunk(columns, lines)
    except UnicodeDecodeError as exc:
        raise ValueError("The file is not valid UTF-8 text.") from exc
    except csv.Error as exc:
        raise ValueError(str(exc)) from exc


def read_table(dataset, names=()) -> tuple[list[str], dict[str, list[str]], list[int]]:
    """Return ``(header, {name: [cell, ...]}, line_numbers)`` for the requested columns."""
    header: list[str] = []
    columns: dict[str, list[str]] = {}
    lines: list[int] = []
    for chunk in iter_chunks(dataset, names, header_out=header):
        for name, cells in chunk.columns.items():
            columns.setdefault(name, []).extend(cells)
        lines.extend(chunk.lines)
    for name in names:
        if name in header:
            columns.setdefault(name, [])
    return header, columns, lines


def read_columns(dataset, names=()) -> tuple[list[str], dict[str, list[str]]]:
    """``read_table`` without the line numbers."""
    header, columns, _ = read_table(dataset, names)
    return header, columns
