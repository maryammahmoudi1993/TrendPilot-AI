"""Detect the sampling frequency of a dataset's timestamps.

Each series (``series_id`` value, or the whole file when there is none) is judged on its
own distinct, sorted timestamps. Two kinds of step are recognised:

* calendar steps (monthly, quarterly, yearly) when the timestamps share a day of the month
  (or are all month ends) and the month distance is mostly 1, 3 or 12;
* fixed steps (``1min`` ... ``hourly``, ``daily``, ``weekly``, ``14D``) when most gaps
  between timestamps equal the most common gap and the rest are multiples of it.

Multiples of the step are reported as missing periods (gaps); a series whose spacing fits
neither rule is ``irregular``. If series disagree the dataset is ``mixed``.
Duplicate timestamps within a series are counted and never treated as a period.
Timezone-aware values are compared in UTC; naive values as wall-clock times.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MIN_POINTS = 3
MAX_GAPS_LISTED = 5
MAX_SERIES_LISTED = 10
# Share of steps that must equal the base step, and that must be multiples of it.
MIN_BASE_SHARE = 0.5
MIN_MULTIPLE_SHARE = 0.9
# Share of the periods between first and last timestamp that must actually be present.
MIN_COVERAGE = 0.5
CALENDAR_STEPS = {1: "monthly", 3: "quarterly", 12: "yearly"}

UNKNOWN = "unknown"
IRREGULAR = "irregular"
MIXED = "mixed"


@dataclass
class SeriesFrequency:
    label: str
    observations: int = 0
    duplicates: int = 0
    missing: int = 0
    gaps: list[dict] = field(default_factory=list)
    longest_gap: int = 0  # most consecutive periods missing in one gap


@dataclass
class FrequencyResult:
    frequency: str
    regular: bool
    consistent: bool
    series_count: int
    observations: int
    duplicates: int
    missing_periods: int
    gaps: list[dict]
    short_series: int
    by_series: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        data = {
            "frequency": self.frequency,
            "regular": self.regular,
            "consistent": self.consistent,
            "series_count": self.series_count,
            "observations": self.observations,
            "duplicates": self.duplicates,
            "missing_periods": self.missing_periods,
            "gaps": self.gaps,
            "short_series": self.short_series,
        }
        if self.by_series:
            data["by_series"] = self.by_series
        return data


def _mode(values: np.ndarray):
    uniques, counts = np.unique(values, return_counts=True)
    top = counts.argmax()
    return uniques[top], counts[top] / len(values)


def _fixed_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        days = seconds // 86400
        return {1: "daily", 7: "weekly"}.get(days, f"{days}D")
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "hourly" if hours == 1 else f"{hours}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return f"{seconds}s"


def _calendar_step(uniq: pd.DatetimeIndex) -> int | None:
    """Return the month step (1, 3 or 12) if the timestamps follow a calendar rhythm."""
    if (uniq - uniq.normalize()).nunique() > 1:  # calendar series share a time of day
        return None
    months = (uniq.year * 12 + uniq.month).to_numpy()
    diffs = np.diff(months)
    step, share = _mode(diffs)
    if int(step) not in CALENDAR_STEPS or share < MIN_BASE_SHARE:
        return None
    same_day = uniq.day.value_counts(normalize=True).iloc[0]
    month_end = uniq.is_month_end.mean()
    if max(same_day, month_end) < MIN_MULTIPLE_SHARE:
        return None
    if np.mean((diffs > 0) & (diffs % step == 0)) < MIN_MULTIPLE_SHARE:
        return None
    return int(step)


def _gaps_from(uniq, periods: np.ndarray) -> tuple[int, list[dict], int]:
    """Missing periods, the first few gaps and the longest one, given each step's length."""
    missing_per = np.maximum(periods - 1, 0)
    missing = int(missing_per.sum())
    gaps = [
        {"after": uniq[i].isoformat(), "missing": int(missing_per[i])}
        for i in np.flatnonzero(missing_per)[:MAX_GAPS_LISTED]
    ]
    return missing, gaps, int(missing_per.max()) if len(missing_per) else 0


def _sparse(series: SeriesFrequency) -> bool:
    return series.observations / (series.observations + series.missing) < MIN_COVERAGE


def _irregular_if_sparse(series: SeriesFrequency) -> SeriesFrequency:
    if _sparse(series):
        series.label, series.missing, series.gaps, series.longest_gap = IRREGULAR, 0, [], 0
    return series


def analyse_series(timestamps: pd.Series) -> SeriesFrequency:
    uniq = pd.DatetimeIndex(timestamps.drop_duplicates().sort_values())
    result = SeriesFrequency(
        UNKNOWN, observations=len(uniq), duplicates=len(timestamps) - len(uniq)
    )
    if len(uniq) < MIN_POINTS:
        return result

    calendar = _calendar_step(uniq)
    if calendar:
        diffs = np.diff((uniq.year * 12 + uniq.month).to_numpy())
        periods = diffs // calendar
        result.label = CALENDAR_STEPS[calendar]
        multiple = (diffs % calendar == 0) & (diffs > 0)
        result.missing, result.gaps, result.longest_gap = _gaps_from(
            uniq, np.where(multiple, periods, 1)
        )
        return _irregular_if_sparse(result)

    seconds = np.rint((uniq[1:] - uniq[:-1]).total_seconds().to_numpy()).astype(np.int64)
    base, share = _mode(seconds)
    if base <= 0 or share < MIN_BASE_SHARE or np.mean(seconds % base == 0) < MIN_MULTIPLE_SHARE:
        result.label = IRREGULAR
        return result
    result.label = _fixed_label(int(base))
    multiple = seconds % base == 0
    result.missing, result.gaps, result.longest_gap = _gaps_from(
        uniq, np.where(multiple, seconds // base, 1)
    )
    return _irregular_if_sparse(result)


def to_timestamps(cells, fmt: str, aware: bool) -> pd.Series:
    """Parse a date column with the format ``dates.detect_date_column`` accepted."""
    return pd.to_datetime(pd.Series([c.strip() for c in cells]), format=fmt, utc=aware or None)


def combine_series(per_series: dict[str, SeriesFrequency]) -> FrequencyResult:
    """Dataset-level result from each series' own analysis (see ``analyse_series``)."""
    multiple = len(per_series) > 1

    labels = {series.label for series in per_series.values() if series.label != UNKNOWN}
    short = sum(1 for series in per_series.values() if series.label == UNKNOWN)
    if not labels:
        frequency = UNKNOWN
    elif len(labels) == 1:
        frequency = next(iter(labels))
    else:
        frequency = MIXED

    gaps: list[dict] = []
    for key, series in per_series.items():
        for gap in series.gaps:
            if len(gaps) < MAX_GAPS_LISTED:
                gaps.append({"series": key, **gap} if multiple else gap)

    return FrequencyResult(
        frequency=frequency,
        regular=frequency not in (UNKNOWN, IRREGULAR, MIXED),
        consistent=frequency != MIXED,
        series_count=len(per_series),
        observations=sum(s.observations for s in per_series.values()),
        duplicates=sum(s.duplicates for s in per_series.values()),
        missing_periods=sum(s.missing for s in per_series.values()),
        gaps=gaps,
        short_series=short,
        by_series=(
            {key: s.label for key, s in list(per_series.items())[:MAX_SERIES_LISTED]}
            if frequency == MIXED
            else {}
        ),
    )


def detect_frequency(timestamps, series_ids=None) -> FrequencyResult:
    """Detect the frequency of ``timestamps`` (parsed datetimes), per ``series_ids``."""
    frame = pd.DataFrame({"ts": pd.Series(timestamps).reset_index(drop=True)})
    frame["id"] = list(series_ids) if series_ids is not None else ""
    return combine_series(
        {str(key): analyse_series(group["ts"]) for key, group in frame.groupby("id", sort=False)}
    )
