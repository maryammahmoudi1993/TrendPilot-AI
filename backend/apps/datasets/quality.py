"""Data-quality report for a mapped dataset.

``build_quality_report(dataset)`` reads the stored CSV in chunks (``columns.iter_chunks``),
converts it with the rules the mapping endpoint used (the date format and decimal
separators the mapping stored, ``numbers.parse_number``, ``frequency.analyse_series``) and
returns a JSON-ready dict. Nothing is removed or altered: outliers, gaps, duplicates and
missing values are only counted and sampled.

Layout (``schema_version`` 1; docs/datasets.md has the field tables)::

    schema_version, severity, summary{info,warning,error}, overview{...}, columns[...],
    findings[{code, severity, message, counts, sample}],
    series{total, listed, truncated, aggregate, items[...]}

Severities: ``info`` is a fact, ``warning`` is something cleaning should look at and
``error`` means modelling cannot proceed (every series too short, or a target without a
single number). The overall severity is the highest finding's, ``ok`` when there are none.
"""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from django.conf import settings

from .columns import iter_chunks
from .frequency import (
    IRREGULAR,
    MIXED,
    SeriesFrequency,
    analyse_series,
    combine_series,
    to_timestamps,
)
from .numbers import MAX_FAILED_LINES, is_missing, parse_number

SCHEMA_VERSION = 1
MAX_SERIES_LISTED = 50
SAMPLE_SIZE = 10
GAPS_LISTED = 5
SEVERITY_RANK = {"ok": 0, "info": 1, "warning": 2, "error": 3}
# Outlier rules, applied per series to the non-missing target values. IQR needs a spread
# (IQR > 0) and the robust z-score needs MAD > 0; a series without one is not tested.
IQR_FENCE = 1.5
ROBUST_Z_LIMIT = 3.5
MAD_TO_SIGMA = 0.6745
MIN_OUTLIER_POINTS = 8
# A series is "near constant" when its most common value makes up this share of it.
NEAR_CONSTANT_SHARE = 0.95
# Negatives are "unusual" only when at least this share of the target is non-negative.
NEGATIVE_MAJORITY_SHARE = 0.95
SEASON_LENGTHS = {"hourly": 24, "daily": 7, "weekly": 52, "monthly": 12, "quarterly": 4}


class QualityReportError(Exception):
    """The report could not be built; the message is safe to show to users."""


@dataclass
class NumericState:
    decimal: str
    converted: int = 0
    empty: int = 0
    failed: int = 0
    failed_lines: list[int] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return self.empty + self.failed


@dataclass
class Loaded:
    frame: pd.DataFrame  # ts, series, target, line
    header_width: int
    target: NumericState
    regressors: dict[str, NumericState]
    series_id_empty: int


def _convert(cells, lines, state: NumericState) -> np.ndarray:
    values = np.full(len(cells), np.nan)
    for i, cell in enumerate(cells):
        if is_missing(cell):
            state.empty += 1
            continue
        number = parse_number(cell, state.decimal)
        if number is None:
            state.failed += 1
            if len(state.failed_lines) < MAX_FAILED_LINES:
                state.failed_lines.append(lines[i])
            continue
        state.converted += 1
        values[i] = number
    return values


def load_frame(dataset, mapping: dict) -> Loaded:
    """Read the mapped columns into one compact frame, chunk by chunk."""
    parsing = mapping["parsing"]
    fmt, aware = mapping["date_format"], parsing["date"]["has_utc_offset"]
    series_col = mapping.get("series_id")
    names = [mapping["date"], mapping["target"], *mapping["regressors"]]
    if series_col:
        names.append(series_col)

    target = NumericState(parsing["target"]["decimal_separator"])
    regressors = {
        name: NumericState(parsing["regressors"][name]["decimal_separator"])
        for name in mapping["regressors"]
    }
    series_empty = 0
    frames = []
    header: list[str] = []
    for chunk in iter_chunks(dataset, names, header_out=header):
        cols = chunk.columns
        if series_col:
            series = cols[series_col]
            series_empty += sum(1 for cell in series if not cell.strip())
        else:
            series = [""] * len(chunk.lines)
        frames.append(
            pd.DataFrame(
                {
                    "ts": to_timestamps(cols[mapping["date"]], fmt, aware),
                    "series": series,
                    "target": _convert(cols[mapping["target"]], chunk.lines, target),
                    "line": np.asarray(chunk.lines, dtype=np.int64),
                }
            )
        )
        for name, state in regressors.items():
            _convert(cols[name], chunk.lines, state)
    if not frames:
        raise QualityReportError("The file has no data rows.")
    return Loaded(
        pd.concat(frames, ignore_index=True), len(header), target, regressors, series_empty
    )


@dataclass
class SeriesStats:
    key: str
    label: str | None
    rows: int
    frequency: SeriesFrequency
    valid: int
    missing_target: int
    first: str
    last: str
    constant: bool = False
    near_constant: bool = False
    outliers_iqr: int = 0
    outliers_z: int = 0
    negatives: int = 0
    sample_iqr: list[dict] = field(default_factory=list)
    sample_z: list[dict] = field(default_factory=list)
    sample_negative: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    severity: str = "info"


def _points(present: pd.DataFrame, mask: np.ndarray, label) -> list[dict]:
    return [
        {
            "series": label,
            "line": int(row.line),
            "timestamp": row.ts.isoformat(),
            "value": float(row.target),
        }
        for row in present[mask].head(SAMPLE_SIZE).itertuples()
    ]


def _outlier_masks(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    none = np.zeros(len(values), dtype=bool)
    if len(values) < MIN_OUTLIER_POINTS:
        return none, none
    q1, q3 = np.quantile(values, [0.25, 0.75])
    spread = q3 - q1
    by_iqr = (values < q1 - IQR_FENCE * spread) | (values > q3 + IQR_FENCE * spread)
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    by_z = np.abs(MAD_TO_SIGMA * (values - median) / mad) > ROBUST_Z_LIMIT if mad > 0 else none
    return (by_iqr if spread > 0 else none), by_z


def _season_length(label: str) -> int | None:
    if label in SEASON_LENGTHS:
        return SEASON_LENGTHS[label]
    for suffix, seconds in (("min", 60), ("h", 3600)):
        if label.endswith(suffix) and label[: -len(suffix)].isdigit():
            step = int(label[: -len(suffix)]) * seconds
            if step < 86400 and 86400 % step == 0:
                return 86400 // step
    return None  # yearly, nD and irregular series have no fixed cycle


def _flag(stats: SeriesStats) -> None:
    low, warn = settings.DATASET_MIN_OBSERVATIONS_ERROR, settings.DATASET_MIN_OBSERVATIONS_WARN
    freq = stats.frequency
    if stats.valid < low:
        stats.flags.append("too_short")
    elif stats.valid < warn:
        stats.flags.append("short")
    for flag, active in (
        ("missing_target", stats.missing_target),
        ("duplicate_timestamps", freq.duplicates),
        ("date_gaps", freq.missing),
        ("constant", stats.constant),
        ("near_constant", stats.near_constant),
        ("irregular", freq.label == IRREGULAR),
    ):
        if active:
            stats.flags.append(flag)
    if "too_short" in stats.flags:
        stats.severity = "error"
    elif stats.flags:
        stats.severity = "warning"
    season = _season_length(freq.label)
    if season and low <= stats.valid < 2 * season:
        stats.flags.append("under_two_seasons")


def _series_stats(key: str, group: pd.DataFrame, has_series: bool) -> SeriesStats:
    label = key if has_series else None
    present = group[group["target"].notna()]
    values = present["target"].to_numpy()
    stats = SeriesStats(
        key=key,
        label=label,
        rows=len(group),
        frequency=analyse_series(group["ts"]),
        valid=len(values),
        missing_target=len(group) - len(values),
        first=group["ts"].min().isoformat(),
        last=group["ts"].max().isoformat(),
    )
    if len(values) >= 2:
        top_share = pd.Series(values).value_counts().iloc[0] / len(values)
        if top_share == 1:
            stats.constant = True
        elif top_share >= NEAR_CONSTANT_SHARE and len(values) >= (
            settings.DATASET_MIN_OBSERVATIONS_ERROR
        ):
            stats.near_constant = True
    by_iqr, by_z = _outlier_masks(values)
    stats.outliers_iqr, stats.outliers_z = int(by_iqr.sum()), int(by_z.sum())
    stats.sample_iqr = _points(present, by_iqr, label)
    stats.sample_z = _points(present, by_z, label)
    negative = values < 0
    stats.negatives = int(negative.sum())
    stats.sample_negative = _points(present, negative, label)
    _flag(stats)
    return stats


def _finding(code, severity, message, counts, sample=None) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "counts": counts,
        "sample": sample or [],
    }


def _observation_rows(stats_list) -> list[dict]:
    rows = [{"series": s.label, "observations": s.valid} for s in stats_list]
    rows.sort(key=lambda r: (r["observations"], str(r["series"])))
    return rows[:SAMPLE_SIZE]


def _length_findings(stats_list) -> list[dict]:
    low, warn = settings.DATASET_MIN_OBSERVATIONS_ERROR, settings.DATASET_MIN_OBSERVATIONS_WARN
    too_short = [s for s in stats_list if "too_short" in s.flags]
    short = [s for s in stats_list if "short" in s.flags]
    found = []
    if too_short:
        every = len(too_short) == len(stats_list)
        message = (
            f"Every series has fewer than {low} usable target values; no model can be fitted."
            if every
            else f"{len(too_short)} of {len(stats_list)} series have fewer than {low} usable "
            "target values."
        )
        found.append(
            _finding(
                "series_too_short",
                "error" if every else "warning",
                message,
                {"series": len(too_short), "of": len(stats_list), "minimum": low},
                _observation_rows(too_short),
            )
        )
    if short:
        found.append(
            _finding(
                "series_short",
                "warning",
                f"{len(short)} series have fewer than {warn} usable target values; forecasts "
                "from so little history are unreliable.",
                {"series": len(short), "minimum": warn},
                _observation_rows(short),
            )
        )
    under = [s for s in stats_list if "under_two_seasons" in s.flags]
    if under:
        found.append(
            _finding(
                "under_two_seasons",
                "info",
                f"{len(under)} series cover fewer than two full seasonal cycles of their "
                "frequency, so seasonal models cannot be checked on them.",
                {"series": len(under)},
                [
                    {"series": s.label, "frequency": s.frequency.label, "observations": s.valid}
                    for s in under[:SAMPLE_SIZE]
                ],
            )
        )
    return found


def _missing_findings(loaded: Loaded, mapping: dict, rows: int) -> list[dict]:
    target, found = loaded.target, []
    if target.converted == 0:
        found.append(
            _finding(
                "target_not_numeric",
                "error",
                f"The target column '{mapping['target']}' has no numeric values.",
                {"rows": rows, "empty": target.empty, "failed": target.failed},
            )
        )
    if target.missing:
        found.append(
            _finding(
                "missing_target",
                "warning",
                f"{target.missing} of {rows} target values are missing "
                f"({target.empty} empty, {target.failed} not numeric).",
                {"missing": target.missing, "empty": target.empty, "failed": target.failed},
            )
        )
    numeric = [(mapping["target"], target), *loaded.regressors.items()]
    failed = [(name, state) for name, state in numeric if state.failed]
    if failed:
        found.append(
            _finding(
                "failed_numeric_conversion",
                "warning",
                "Some cells could not be converted to numbers and were kept as missing values.",
                {
                    "cells": sum(state.failed for _, state in failed),
                    "columns": {name: state.failed for name, state in failed},
                },
                [{"column": name, "lines": state.failed_lines} for name, state in failed],
            )
        )
    gaps = {name: state.missing for name, state in loaded.regressors.items() if state.missing}
    if gaps:
        found.append(
            _finding(
                "missing_regressors",
                "info",
                "Some regressor values are missing.",
                {"cells": sum(gaps.values()), "columns": gaps},
            )
        )
    if loaded.series_id_empty:
        found.append(
            _finding(
                "missing_series_id",
                "warning",
                f"{loaded.series_id_empty} rows have an empty series id; they are grouped "
                "together as one series.",
                {"rows": loaded.series_id_empty},
            )
        )
    return found


def _upload_findings(upload_report: dict) -> list[dict]:
    ragged = (upload_report or {}).get("ragged") or {}
    blank = (upload_report or {}).get("blank_lines", 0)
    found = []
    if ragged.get("count"):
        found.append(
            _finding(
                "ragged_rows",
                "warning",
                f"{ragged['count']} rows had a different number of fields than the header; "
                "short rows were padded and long rows truncated.",
                {
                    "rows": ragged["count"],
                    "short": ragged.get("short", 0),
                    "long": ragged.get("long", 0),
                },
                [{"line": line} for line in ragged.get("lines", [])],
            )
        )
    if blank:
        found.append(
            _finding("blank_lines", "info", f"{blank} blank lines were skipped.", {"lines": blank})
        )
    return found


def _timestamp_findings(stats_list, dataset_freq) -> list[dict]:
    found = []
    duplicated = [s for s in stats_list if s.frequency.duplicates]
    if duplicated:
        total = sum(s.frequency.duplicates for s in duplicated)
        sample = sorted(
            ({"series": s.label, "duplicates": s.frequency.duplicates} for s in duplicated),
            key=lambda r: (-r["duplicates"], str(r["series"])),
        )
        found.append(
            _finding(
                "duplicate_timestamps",
                "warning",
                f"{total} rows repeat a timestamp already present in their series.",
                {"duplicates": total, "series": len(duplicated)},
                sample[:SAMPLE_SIZE],
            )
        )
    gapped = [s for s in stats_list if s.frequency.missing]
    if gapped:
        gaps = [{"series": s.label, **gap} for s in gapped for gap in s.frequency.gaps]
        found.append(
            _finding(
                "date_gaps",
                "warning",
                f"{sum(s.frequency.missing for s in gapped)} expected periods are missing "
                "from the timestamps.",
                {
                    "missing_periods": sum(s.frequency.missing for s in gapped),
                    "series": len(gapped),
                    "longest_gap": max(s.frequency.longest_gap for s in gapped),
                },
                gaps[:GAPS_LISTED],
            )
        )
    irregular = [s for s in stats_list if s.frequency.label == IRREGULAR]
    if irregular:
        found.append(
            _finding(
                "irregular_frequency",
                "warning",
                f"{len(irregular)} series have no regular sampling frequency.",
                {"series": len(irregular)},
                [{"series": s.label} for s in irregular[:SAMPLE_SIZE]],
            )
        )
    if dataset_freq.frequency == MIXED:
        found.append(
            _finding(
                "mixed_frequency",
                "warning",
                "The series are sampled at different frequencies.",
                {"frequencies": dict(Counter(s.frequency.label for s in stats_list))},
            )
        )
    return found


def _collect(stats_list, attr) -> list[dict]:
    return [point for s in stats_list for point in getattr(s, attr)][:SAMPLE_SIZE]


def _value_findings(stats_list) -> list[dict]:
    found = []
    for code, count_attr, sample_attr, rule in (
        (
            "outliers_iqr",
            "outliers_iqr",
            "sample_iqr",
            f"outside {IQR_FENCE} x IQR of the quartiles",
        ),
        (
            "outliers_robust_z",
            "outliers_z",
            "sample_z",
            f"with a robust z-score (median/MAD) above {ROBUST_Z_LIMIT}",
        ),
    ):
        total = sum(getattr(s, count_attr) for s in stats_list)
        if total:
            found.append(
                _finding(
                    code,
                    "info",
                    f"{total} target values are {rule}. They were kept unchanged.",
                    {
                        "values": total,
                        "series": sum(1 for s in stats_list if getattr(s, count_attr)),
                    },
                    _collect(stats_list, sample_attr),
                )
            )
    constant = [s for s in stats_list if s.constant]
    if constant:
        found.append(
            _finding(
                "constant_series",
                "warning",
                f"{len(constant)} series have the same target value in every row.",
                {"series": len(constant)},
                [{"series": s.label, "observations": s.valid} for s in constant[:SAMPLE_SIZE]],
            )
        )
    near = [s for s in stats_list if s.near_constant]
    if near:
        found.append(
            _finding(
                "near_constant_series",
                "warning",
                f"{len(near)} series repeat one value in at least {NEAR_CONSTANT_SHARE:.0%} "
                "of their rows.",
                {"series": len(near)},
                [{"series": s.label, "observations": s.valid} for s in near[:SAMPLE_SIZE]],
            )
        )
    negatives = sum(s.negatives for s in stats_list)
    observed = sum(s.valid for s in stats_list)
    if negatives and (observed - negatives) / observed >= NEGATIVE_MAJORITY_SHARE:
        found.append(
            _finding(
                "unusual_negatives",
                "warning",
                f"{negatives} target values are negative although at least "
                f"{NEGATIVE_MAJORITY_SHARE:.0%} of the target is non-negative.",
                {"values": negatives, "observed": observed},
                _collect(stats_list, "sample_negative"),
            )
        )
    return found


def _series_item(s: SeriesStats) -> dict:
    return {
        "series": s.label,
        "severity": s.severity,
        "rows": s.rows,
        "observations": s.valid,
        "missing_target": s.missing_target,
        "first": s.first,
        "last": s.last,
        "frequency": s.frequency.label,
        "duplicate_timestamps": s.frequency.duplicates,
        "missing_periods": s.frequency.missing,
        "longest_gap": s.frequency.longest_gap,
        "outliers_iqr": s.outliers_iqr,
        "outliers_robust_z": s.outliers_z,
        "flags": s.flags,
    }


def _series_section(stats_list) -> dict:
    ordered = sorted(
        stats_list,
        key=lambda s: (-SEVERITY_RANK[s.severity], -len(s.flags), s.key),
    )
    listed = ordered[:MAX_SERIES_LISTED]
    return {
        "total": len(stats_list),
        "listed": len(listed),
        "truncated": len(stats_list) > MAX_SERIES_LISTED,
        "order": "worst first",
        "aggregate": {
            "with_errors": sum(1 for s in stats_list if s.severity == "error"),
            "with_warnings": sum(1 for s in stats_list if s.severity == "warning"),
            "clean": sum(1 for s in stats_list if s.severity == "info"),
        },
        "items": [_series_item(s) for s in listed],
    }


def _column_rows(loaded: Loaded, mapping: dict, rows: int) -> list[dict]:
    def entry(name, role, missing, empty, failed):
        return {
            "name": name,
            "role": role,
            "missing": missing,
            "empty": empty,
            "failed": failed,
            "missing_share": round(missing / rows, 6) if rows else 0,
        }

    result = [entry(mapping["date"], "date", 0, 0, 0)]
    if mapping.get("series_id"):
        empty = loaded.series_id_empty
        result.append(entry(mapping["series_id"], "series_id", empty, empty, 0))
    target = loaded.target
    result.append(entry(mapping["target"], "target", target.missing, target.empty, target.failed))
    for name, state in loaded.regressors.items():
        result.append(entry(name, "regressor", state.missing, state.empty, state.failed))
    return result


def build_report(loaded: Loaded, mapping: dict, upload_report: dict) -> dict:
    """Pure analysis of a loaded frame; see the module docstring."""
    frame = loaded.frame
    has_series = bool(mapping.get("series_id"))
    stats_list = [
        _series_stats(str(key), group, has_series)
        for key, group in frame.groupby("series", sort=False)
    ]
    dataset_freq = combine_series({s.key: s.frequency for s in stats_list})
    rows = len(frame)

    findings = [
        *_missing_findings(loaded, mapping, rows),
        *_length_findings(stats_list),
        *_upload_findings(upload_report),
        *_timestamp_findings(stats_list, dataset_freq),
        *_value_findings(stats_list),
    ]
    truncated = len(stats_list) > MAX_SERIES_LISTED
    if truncated:
        findings.append(
            _finding(
                "series_summaries_truncated",
                "info",
                f"Only the {MAX_SERIES_LISTED} worst of {len(stats_list)} series are listed "
                "individually; the counts in this report cover all of them.",
                {"series": len(stats_list), "listed": MAX_SERIES_LISTED},
            )
        )
    findings.sort(key=lambda f: -SEVERITY_RANK[f["severity"]])  # stable: emission order kept
    summary = {
        s: sum(1 for f in findings if f["severity"] == s) for s in ("info", "warning", "error")
    }
    severity = max((f["severity"] for f in findings), key=SEVERITY_RANK.get, default="ok")

    return {
        "schema_version": SCHEMA_VERSION,
        "severity": severity,
        "summary": summary,
        "overview": {
            "rows": rows,
            "columns": loaded.header_width,
            "series": len(stats_list),
            "date_range": {
                "start": frame["ts"].min().isoformat(),
                "end": frame["ts"].max().isoformat(),
            },
            "frequency": dataset_freq.frequency,
            "frequencies": dict(sorted(Counter(s.frequency.label for s in stats_list).items())),
            "target": mapping["target"],
            "series_id": mapping.get("series_id"),
            "regressors": list(mapping["regressors"]),
        },
        "columns": _column_rows(loaded, mapping, rows),
        "findings": findings,
        "series": _series_section(stats_list),
    }


def blocking_reason(report: dict) -> str:
    """Readable reason when the report holds error findings, else an empty string."""
    return " ".join(f["message"] for f in report["findings"] if f["severity"] == "error")


def build_quality_report(dataset) -> dict:
    """Read ``dataset``'s file and return its quality report. Needs a saved mapping."""
    mapping = dataset.column_mapping
    if not mapping.get("date") or not mapping.get("target"):
        raise QualityReportError("The dataset has no column mapping.")
    return build_report(load_frame(dataset, mapping), mapping, dataset.upload_report)
