"""Read selected columns of a stored dataset CSV as raw strings."""

import csv
import io

from .validation import detect_dialect


def read_columns(dataset, names=()) -> tuple[list[str], dict[str, list[str]]]:
    """Return ``(header, {name: [cell, ...]})`` for the requested column names.

    Short rows are padded with empty strings. Names missing from the header are skipped;
    callers check the header first.
    """
    with dataset.file.open("rb") as handle:
        text = handle.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text), detect_dialect(text))
    header = next(reader)
    wanted = {name: header.index(name) for name in names if name in header}
    columns: dict[str, list[str]] = {name: [] for name in wanted}
    for row in reader:
        for name, idx in wanted.items():
            columns[name].append(row[idx] if idx < len(row) else "")
    return header, columns
