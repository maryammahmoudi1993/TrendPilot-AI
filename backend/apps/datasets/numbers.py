"""Numeric coercion for CSV cells: thousand separators and decimal commas.

The decimal separator is decided per column, not per cell: ``1,234`` alone could be
one thousand two hundred thirty-four or 1.234, so the whole column is inspected first.
Decisive evidence (``1.234,56``, ``12,5``, ``1,234,567``) settles it; a column whose only
evidence is ambiguous (``1,234``) is read with ``,`` as a thousands separator and flagged
``ambiguous`` so the caller can ask for an explicit ``decimal_separator``.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

MISSING_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none", "-", "--"})
MAX_EXAMPLES = 5
MAX_FAILED_LINES = 20

_GROUP_SPACES = "   '’"
_SIGNS = {"+": 1, "-": -1, "−": -1}
_EXPONENT = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
_BODY = re.compile(r"^\d[\d.,]*\d$|^\d$")


def is_missing(cell: str) -> bool:
    return cell.strip().lower() in MISSING_TOKENS


def _split_sign(cell: str) -> tuple[int, str]:
    text = cell.strip()
    sign = 1
    if text and text[0] in _SIGNS:
        sign, text = _SIGNS[text[0]], text[1:]
    for ch in _GROUP_SPACES:
        text = text.replace(ch, "")
    return sign, text


def _valid_grouping(text: str, thousands: str) -> bool:
    """Digits grouped by ``thousands``: 1-3 digits, then groups of exactly three."""
    parts = text.split(thousands)
    return 1 <= len(parts[0]) <= 3 and all(len(p) == 3 and p.isdigit() for p in parts[1:])


def _evidence(body: str) -> tuple[str, str | None]:
    """Classify one cell body. Returns ``(kind, separator)``.

    kind: ``plain`` (no separator), ``decimal`` (separator is the decimal mark),
    ``thousands`` (separator groups thousands), ``ambiguous`` (a single separator
    followed by exactly three digits), or ``invalid``.
    """
    if not _BODY.match(body):
        return "invalid", None
    commas, dots = body.count(","), body.count(".")
    if not commas and not dots:
        return "plain", None
    if commas and dots:
        decimal = "," if body.rfind(",") > body.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        head, _, tail = body.rpartition(decimal)
        if body.count(decimal) != 1 or not tail.isdigit() or not _valid_grouping(head, thousands):
            return "invalid", None
        return "decimal", decimal
    sep = "," if commas else "."
    count = commas or dots
    if count > 1:
        return ("thousands", sep) if _valid_grouping(body, sep) else ("invalid", None)
    left, right = body.split(sep)
    if not left or not right:
        return "invalid", None
    if len(right) == 3 and 1 <= len(left) <= 3 and left != "0":
        return "ambiguous", sep
    return "decimal", sep


def parse_number(cell: str, decimal: str = ".") -> float | None:
    """Parse one cell with a known decimal separator (``.`` or ``,``); ``None`` if invalid."""
    thousands = "," if decimal == "." else "."
    sign, body = _split_sign(cell)
    if _EXPONENT.match(body):
        return sign * float(body)
    if not _BODY.match(body):
        return None
    if thousands in body:
        whole, _, frac = body.partition(decimal)
        if not _valid_grouping(whole, thousands) or (frac and not frac.isdigit()):
            return None
        body = whole.replace(thousands, "") + ("." + frac if frac else "")
    elif body.count(decimal) > 1:
        return None
    else:
        body = body.replace(decimal, ".")
    try:
        return sign * float(body)
    except ValueError:
        return None


@dataclass
class NumericColumnResult:
    decimal_separator: str
    thousands_separator: str
    ambiguous: bool
    converted: int = 0
    empty: int = 0
    failed: int = 0
    failed_examples: list[str] = field(default_factory=list)
    failed_lines: list[int] = field(default_factory=list)

    @property
    def missing(self) -> int:
        """Empty cells plus cells that failed conversion; both are treated as missing."""
        return self.empty + self.failed

    @property
    def non_empty(self) -> int:
        return self.converted + self.failed

    def as_dict(self) -> dict:
        return {
            "decimal_separator": self.decimal_separator,
            "thousands_separator": self.thousands_separator,
            "ambiguous_separator": self.ambiguous,
            "converted": self.converted,
            "empty": self.empty,
            "failed": self.failed,
            "failed_examples": self.failed_examples,
            "failed_lines": self.failed_lines,
            "missing": self.missing,
        }


def detect_decimal_separator(cells, hint: str | None = None) -> tuple[str, bool]:
    """Return ``(decimal_separator, ambiguous)`` for a column. ``hint`` wins if given."""
    if hint:
        return hint, False
    votes: Counter = Counter()
    ambiguous_seen = False
    for cell in cells:
        if is_missing(cell):
            continue
        _, body = _split_sign(cell)
        kind, sep = _evidence(body)
        if kind == "decimal":
            votes[sep] += 1
        elif kind == "thousands":
            votes["." if sep == "," else ","] += 1
        elif kind == "ambiguous":
            ambiguous_seen = True
    if votes:
        return votes.most_common(1)[0][0], False
    return ".", ambiguous_seen


def parse_numeric_column(cells, decimal_hint: str | None = None, lines=None) -> NumericColumnResult:
    """Coerce a column of strings; count converted, empty and failed cells.

    ``lines`` gives the file line number of each cell; by default cell ``i`` is on line
    ``i + 2`` (the header is line 1).
    """
    cells = list(cells)
    decimal, ambiguous = detect_decimal_separator(cells, decimal_hint)
    result = NumericColumnResult(decimal, "," if decimal == "." else ".", ambiguous)
    for index, cell in enumerate(cells):
        if is_missing(cell):
            result.empty += 1
        elif parse_number(cell, decimal) is None:
            result.failed += 1
            if len(result.failed_examples) < MAX_EXAMPLES:
                result.failed_examples.append(cell)
            if len(result.failed_lines) < MAX_FAILED_LINES:
                result.failed_lines.append(lines[index] if lines else index + 2)
        else:
            result.converted += 1
    return result
