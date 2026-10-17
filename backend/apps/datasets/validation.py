"""CSV sniffing used to validate an uploaded dataset before it is stored."""

import csv
import io
from collections import Counter

from django.conf import settings

MAX_SNIFF_BYTES = 64 * 1024
ALLOWED_DELIMITERS = ",;\t"
# The delimiter must give the same field count on at least this share of sampled rows.
MIN_DELIMITER_SHARE = 0.5
MAX_RAGGED_LINES_STORED = 10
MAX_RAGGED_LINES_LISTED = 5


class CsvSniffError(Exception):
    """Raised with a user-facing message when the uploaded bytes aren't a usable CSV."""


def detect_dialect(text: str):
    """Pick the delimiter (comma, semicolon or tab) that splits the sample most evenly.

    Each candidate is scored by how many sampled rows share its most common field count;
    that count must be at least two. Unlike ``csv.Sniffer`` this tolerates ragged rows, so
    a short trailing line cannot hide the delimiter.
    """
    sample = text[:MAX_SNIFF_BYTES]
    if len(text) > MAX_SNIFF_BYTES:
        sample = sample[: sample.rfind("\n") + 1] or sample
    best, best_key = None, None
    for delimiter in ALLOWED_DELIMITERS:
        widths = [len(row) for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if row]
        if not widths:
            continue
        width, count = Counter(widths).most_common(1)[0]
        share = count / len(widths)
        if width < 2 or share < MIN_DELIMITER_SHARE:
            continue
        if best_key is None or (share, width) > best_key:
            best, best_key = delimiter, (share, width)
    if best is None:
        raise CsvSniffError("Could not detect a comma, semicolon or tab delimiter.")

    class Detected(csv.excel):
        delimiter = best

    return Detected


def _allowed_ragged(row_count: int) -> int:
    """Rows allowed to differ from the header width: a share of the file, at least one."""
    share = settings.DATASET_MAX_RAGGED_SHARE
    if share <= 0:
        return 0
    return max(1, int(share * row_count))


def sniff_csv(raw: bytes) -> dict:
    """Validate ``raw`` as CSV text; return delimiter, header, row_count, blank_lines, ragged.

    Rows with fewer fields than the header are padded and rows with more are truncated when
    the data is read; ``ragged`` records how many there were (``count``, ``short``,
    ``long``) and the first few file line numbers. More ragged rows than
    ``DATASET_MAX_RAGGED_SHARE`` of the file allows is an error, as is anything that isn't
    a usable CSV: binary content, bad encoding, an unrecognised delimiter, or no data rows.
    """
    if b"\x00" in raw:
        raise CsvSniffError("The file looks like binary data, not a CSV.")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvSniffError("The file is not valid UTF-8 text.") from exc

    dialect = detect_dialect(text)

    # detect_dialect only succeeds once it has seen at least one row, so there is a header.
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader)
    row_count = blank = short = long = 0
    lines: list[int] = []
    for row in reader:
        if not row:  # blank lines are neither data rows nor ragged rows
            blank += 1
            continue
        row_count += 1
        if len(row) == len(header):
            continue
        if len(row) < len(header):
            short += 1
        else:
            long += 1
        if len(lines) < MAX_RAGGED_LINES_STORED:
            lines.append(reader.line_num)
    if row_count == 0:
        raise CsvSniffError("The file has a header but no data rows.")

    ragged = short + long
    if ragged > _allowed_ragged(row_count):
        listed = ", ".join(str(n) for n in lines[:MAX_RAGGED_LINES_LISTED])
        raise CsvSniffError(
            f"{ragged} of {row_count} rows do not have the same number of fields as the "
            f"header (limit {settings.DATASET_MAX_RAGGED_SHARE:.0%} of rows). "
            f"The first ones are on lines {listed}."
        )

    return {
        "delimiter": dialect.delimiter,
        "header": header,
        "row_count": row_count,
        "blank_lines": blank,
        "ragged": {"count": ragged, "short": short, "long": long, "lines": lines},
    }
