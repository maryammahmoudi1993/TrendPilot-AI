"""Explicit date-format detection for a CSV column.

Instead of guessing, the column is matched against a fixed list of ``strptime`` formats.
A format is accepted only if it parses *every* value. When both a day-first and a
month-first format fit (``03/04/2024``), the column is reported as ambiguous and the
caller must supply ``date_order``. Values with a UTC offset (``Z``, ``+02:00``) are aware;
naive values may be tied to an IANA timezone supplied by the caller.
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_EXAMPLES = 5
SAMPLE_SIZE = 200

DATE_ORDERS = ("dmy", "mdy")


@dataclass(frozen=True)
class DateFormat:
    fmt: str
    order: str  # ymd, dmy, mdy, text, ym
    aware: bool


def _build_formats() -> list[DateFormat]:
    dates = [
        ("%Y-%m-%d", "ymd", True),
        ("%Y/%m/%d", "ymd", False),
        ("%Y.%m.%d", "ymd", False),
        ("%d/%m/%Y", "dmy", False),
        ("%d-%m-%Y", "dmy", False),
        ("%d.%m.%Y", "dmy", False),
        ("%m/%d/%Y", "mdy", False),
        ("%m-%d-%Y", "mdy", False),
        ("%m.%d.%Y", "mdy", False),
        ("%d %b %Y", "text", False),
        ("%d %B %Y", "text", False),
        ("%d-%b-%Y", "text", False),
        ("%b %d, %Y", "text", False),
        ("%B %d, %Y", "text", False),
    ]
    formats = [DateFormat("%Y-%m", "ym", False)]
    for date_fmt, order, iso_like in dates:
        separators = [" ", "T"] if iso_like else [" "]
        times = [""] + [sep + t for sep in separators for t in ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f")]
        for time in times:
            formats.append(DateFormat(date_fmt + time, order, False))
            if time:
                formats.append(DateFormat(date_fmt + time + "%z", order, True))
    return formats


CANDIDATE_FORMATS = _build_formats()


@dataclass
class DateColumnResult:
    ok: bool
    code: str = ""  # when not ok: ambiguous_date_order, mixed_date_formats, unparseable_dates
    message: str = ""
    format: str = ""
    order: str = ""
    aware: bool = False
    timezone: str | None = None
    parsed: int = 0
    bad_count: int = 0
    bad_examples: list[str] = field(default_factory=list)
    earliest: str = ""
    latest: str = ""
    candidate_orders: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = {
            "format": self.format,
            "order": self.order,
            "has_utc_offset": self.aware,
            "timezone": self.timezone,
            "parsed": self.parsed,
            "earliest": self.earliest,
            "latest": self.latest,
        }
        return data


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"Unknown timezone '{name}'.") from exc
    return name


def _try(value: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def _parse_distinct(distinct, formats: list[DateFormat]):
    """Return ``{format: {value: datetime}}`` and the values each format failed on."""
    parsed = {f: {} for f in formats}
    failures = {f: [] for f in formats}
    for value in distinct:
        for f in formats:
            dt = _try(value, f.fmt)
            if dt is None:
                failures[f].append(value)
            else:
                parsed[f][value] = dt
    return parsed, failures


def detect_date_column(cells, order_hint: str | None = None, timezone: str | None = None):
    """Detect the format of a date column. See the module docstring for the rules."""
    cells = [c.strip() for c in cells]
    blanks = sum(1 for c in cells if not c)
    distinct = sorted({c for c in cells if c})
    if not distinct:
        return DateColumnResult(
            ok=False,
            code="unparseable_dates",
            message="The date column has no values.",
            bad_count=blanks,
            bad_examples=["<empty>"] if blanks else [],
        )

    formats = [f for f in CANDIDATE_FORMATS if order_hint is None or f.order not in DATE_ORDERS]
    if order_hint:
        formats += [f for f in CANDIDATE_FORMATS if f.order == order_hint]

    # Shortlist on a sample, then verify the shortlisted formats on every distinct value.
    sample = distinct[:SAMPLE_SIZE]
    _, sample_failures = _parse_distinct(sample, formats)
    shortlist = [f for f in formats if not sample_failures[f]]
    if not shortlist:
        ranked = sorted(formats, key=lambda f: len(sample_failures[f]))
        shortlist = ranked[:3]

    parsed, failures = _parse_distinct(distinct, shortlist)
    full = [f for f in shortlist if not failures[f]]

    if blanks == 0 and full:
        orders = {f.order for f in full}
        if {"dmy", "mdy"} <= orders:
            return DateColumnResult(
                ok=False,
                code="ambiguous_date_order",
                message=(
                    "The dates fit both day-first and month-first. Set date_order to "
                    "'dmy' or 'mdy'."
                ),
                candidate_orders=["dmy", "mdy"],
            )
        chosen = full[0]
        values = list(parsed[chosen].values())
        tz = None if chosen.aware else timezone
        return DateColumnResult(
            ok=True,
            format=chosen.fmt,
            order=chosen.order,
            aware=chosen.aware,
            timezone=tz,
            parsed=len(cells),
            earliest=min(values).isoformat(),
            latest=max(values).isoformat(),
        )

    best = min(shortlist, key=lambda f: len(failures[f]))
    bad_values = set(failures[best])
    others_parse = any(
        parsed[f].get(v) is not None for v in bad_values for f in shortlist if f is not best
    )
    bad_cells = [c if c else "<empty>" for c in cells if not c or c in bad_values]
    code = "mixed_date_formats" if others_parse else "unparseable_dates"
    if code == "mixed_date_formats":
        message = "The date column mixes several formats; use one format throughout."
    else:
        message = "Some values in the date column could not be parsed."
    return DateColumnResult(
        ok=False,
        code=code,
        message=message,
        format=best.fmt,
        parsed=len(cells) - len(bad_cells),
        bad_count=len(bad_cells),
        bad_examples=list(dict.fromkeys(bad_cells))[:MAX_EXAMPLES],
    )
