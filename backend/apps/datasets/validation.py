"""CSV sniffing used to validate an uploaded dataset before it is stored."""

import csv
import io

MAX_SNIFF_BYTES = 64 * 1024
ALLOWED_DELIMITERS = ",;\t"


class CsvSniffError(Exception):
    """Raised with a user-facing message when the uploaded bytes aren't a usable CSV."""


def detect_dialect(text: str):
    """Sniff the delimiter of decoded CSV text (comma, semicolon or tab only)."""
    try:
        return csv.Sniffer().sniff(text[:MAX_SNIFF_BYTES], delimiters=ALLOWED_DELIMITERS)
    except csv.Error as exc:
        raise CsvSniffError("Could not detect a comma, semicolon or tab delimiter.") from exc


def sniff_csv(raw: bytes) -> dict:
    """Validate ``raw`` as CSV text and return ``{"delimiter", "header", "row_count"}``.

    Raises ``CsvSniffError`` with a human-readable message for anything that isn't a
    usable CSV: binary content, bad encoding, an unrecognised delimiter, or no data rows.
    """
    if b"\x00" in raw:
        raise CsvSniffError("The file looks like binary data, not a CSV.")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvSniffError("The file is not valid UTF-8 text.") from exc

    dialect = detect_dialect(text)

    # The Sniffer above only succeeds once it has seen at least one delimited line,
    # so the reader always has a header row to give here.
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader)
    row_count = sum(1 for _ in reader)
    if row_count == 0:
        raise CsvSniffError("The file has a header but no data rows.")

    return {"delimiter": dialect.delimiter, "header": header, "row_count": row_count}
