import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from apps.datasets.quality import (
    Loaded,
    NumericState,
    QualityReportError,
    blocking_reason,
    build_quality_report,
    build_report,
)
from apps.datasets.services import update_mapping
from tests.helpers import make_dataset

pytestmark = pytest.mark.django_db

START = date(2024, 1, 1)


@pytest.fixture
def ws(two_workspaces):
    return two_workspaces["a"]["workspace"]


def day(n: int) -> str:
    return (START + timedelta(days=n)).isoformat()


def mapped(ws, text, **mapping):
    dataset = make_dataset(ws, text)
    update_mapping(
        dataset=dataset,
        actor=None,
        data={"date": "date", "target": "sales", **mapping},
        partial=False,
    )
    dataset.refresh_from_db()
    return dataset


def codes(report):
    return {f["code"]: f for f in report["findings"]}


def daily_rows(n, value=lambda i: 100 + i % 7, skip=()):
    return [(day(i), value(i)) for i in range(n) if i not in skip]


def csv_of(rows, header="date,sales"):
    return header + "\n" + "\n".join(",".join(str(c) for c in row) for row in rows) + "\n"


# --- one series with every defect injected at a known place -------------------------------

SKIPPED_DAYS = {50, 51, 52, 100}  # one gap of 3 periods and one of 1


@pytest.fixture
def defective(ws):
    rows = [[d, v, 20 + i % 5] for i, (d, v) in enumerate(daily_rows(200, skip=SKIPPED_DAYS))]
    rows.insert(11, list(rows[10]))  # duplicate timestamps
    rows.insert(22, list(rows[21]))
    for i in (30, 60, 90):
        rows[i][1] = ""  # empty target
    rows[120][1] = "abc"  # target that is not a number
    rows[140][1] = 10000  # high outliers
    rows[150][1] = 12000
    rows[160][1] = -5  # negatives (also outliers)
    rows[170][1] = -7
    for i in (5, 70, 80, 130):
        rows[i][2] = ""  # empty regressor cells
    lines = [",".join(str(c) for c in r) for r in rows]
    lines.append(f"{day(200)},105")  # short row: the regressor is missing
    lines.insert(40, "")  # a blank line
    text = "date,sales,temp\n" + "\n".join(lines) + "\n"
    dataset = mapped(ws, text, regressors=["temp"])
    file_lines = text.split("\n")
    return {
        "dataset": dataset,
        "report": build_quality_report(dataset),
        "abc_line": next(i + 1 for i, line in enumerate(file_lines) if ",abc," in line),
        "total_rows": len(rows) + 1,
    }


def test_exactly_the_injected_defects_are_found(defective):
    assert set(codes(defective["report"])) == {
        "missing_target",
        "failed_numeric_conversion",
        "missing_regressors",
        "ragged_rows",
        "blank_lines",
        "duplicate_timestamps",
        "date_gaps",
        "outliers_iqr",
        "outliers_robust_z",
        "unusual_negatives",
    }
    assert defective["report"]["severity"] == "warning"


def test_overview_and_columns(defective):
    report, total = defective["report"], defective["total_rows"]
    assert report["schema_version"] == 1
    overview = report["overview"]
    assert overview["rows"] == total
    assert overview["columns"] == 3
    assert overview["series"] == 1
    assert overview["frequency"] == "daily"
    assert overview["date_range"] == {
        "start": pd.Timestamp(day(0)).isoformat(),
        "end": pd.Timestamp(day(200)).isoformat(),
    }
    by_name = {c["name"]: c for c in report["columns"]}
    assert by_name["sales"]["missing"] == 4 and by_name["sales"]["empty"] == 3
    assert by_name["sales"]["failed"] == 1
    assert by_name["sales"]["missing_share"] == round(4 / total, 6)
    assert by_name["temp"]["role"] == "regressor"
    assert by_name["temp"]["missing"] == 5  # four empty cells plus the padded short row
    assert by_name["date"]["missing"] == 0


def test_missing_and_failed_values(defective):
    found = codes(defective["report"])
    assert found["missing_target"]["counts"] == {"missing": 4, "empty": 3, "failed": 1}
    failed = found["failed_numeric_conversion"]
    assert failed["counts"] == {"cells": 1, "columns": {"sales": 1}}
    assert failed["sample"] == [{"column": "sales", "lines": [defective["abc_line"]]}]
    assert found["missing_regressors"]["counts"] == {"cells": 5, "columns": {"temp": 5}}
    assert found["missing_regressors"]["severity"] == "info"


def test_upload_findings(defective):
    found = codes(defective["report"])
    assert found["ragged_rows"]["counts"] == {"rows": 1, "short": 1, "long": 0}
    assert len(found["ragged_rows"]["sample"]) == 1
    assert found["blank_lines"]["counts"] == {"lines": 1}
    assert found["blank_lines"]["severity"] == "info"


def test_duplicate_timestamps_and_gaps(defective):
    found = codes(defective["report"])
    assert found["duplicate_timestamps"]["counts"] == {"duplicates": 2, "series": 1}
    gaps = found["date_gaps"]
    assert gaps["counts"] == {"missing_periods": 4, "series": 1, "longest_gap": 3}
    assert [(g["after"], g["missing"]) for g in gaps["sample"]] == [
        (pd.Timestamp(day(49)).isoformat(), 3),
        (pd.Timestamp(day(99)).isoformat(), 1),
    ]


def test_outliers_are_counted_and_never_removed(defective):
    found = codes(defective["report"])
    for code in ("outliers_iqr", "outliers_robust_z"):
        assert found[code]["counts"] == {"values": 4, "series": 1}
        assert found[code]["severity"] == "info"
        assert {p["value"] for p in found[code]["sample"]} == {10000.0, 12000.0, -5.0, -7.0}
    assert defective["report"]["overview"]["rows"] == defective["total_rows"]


def test_unusual_negatives(defective):
    found = codes(defective["report"])["unusual_negatives"]
    assert found["counts"] == {"values": 2, "observed": defective["total_rows"] - 4}
    assert sorted(p["value"] for p in found["sample"]) == [-7.0, -5.0]


def test_report_agrees_with_the_mapping_endpoint(defective):
    dataset, report = defective["dataset"], defective["report"]
    parsing = dataset.column_mapping["parsing"]
    columns = {c["name"]: c for c in report["columns"]}
    for name, stats in (("sales", parsing["target"]), ("temp", parsing["regressors"]["temp"])):
        assert columns[name]["empty"] == stats["empty"]
        assert columns[name]["failed"] == stats["failed"]
        assert columns[name]["missing"] == stats["missing"]
    found = codes(report)
    assert found["failed_numeric_conversion"]["sample"][0]["lines"] == (
        parsing["target"]["failed_lines"]
    )
    frequency = parsing["frequency"]
    assert report["overview"]["frequency"] == frequency["frequency"] == dataset.detected_frequency
    assert found["duplicate_timestamps"]["counts"]["duplicates"] == frequency["duplicates"]
    assert found["date_gaps"]["counts"]["missing_periods"] == frequency["missing_periods"]
    assert [(g["after"], g["missing"]) for g in found["date_gaps"]["sample"]] == [
        (g["after"], g["missing"]) for g in frequency["gaps"]
    ]
    assert report["series"]["items"][0]["observations"] + columns["sales"]["missing"] == (
        report["overview"]["rows"]
    )


def test_the_report_is_deterministic_and_independent_of_chunk_size(defective, settings):
    first = build_quality_report(defective["dataset"])
    settings.DATASET_READ_CHUNK_ROWS = 7
    again = build_quality_report(defective["dataset"])
    assert json.dumps(first) == json.dumps(again) == json.dumps(defective["report"])


def test_the_report_is_json_serialisable(defective):
    assert json.loads(json.dumps(defective["report"])) == defective["report"]


# --- clean data ----------------------------------------------------------------------------


def test_a_clean_series_has_no_findings(ws):
    report = build_quality_report(mapped(ws, csv_of(daily_rows(120))))
    assert report["findings"] == []
    assert report["severity"] == "ok"
    assert report["summary"] == {"info": 0, "warning": 0, "error": 0}
    item = report["series"]["items"][0]
    assert item["series"] is None and item["severity"] == "info" and item["flags"] == []
    assert item["observations"] == 120 and item["frequency"] == "daily"


# --- series length, constants, seasonality -------------------------------------------------


def multi_csv(spec):
    """spec: {series: [(date, value), ...]}"""
    rows = [(d, s, v) for s, points in spec.items() for d, v in points]
    return csv_of(rows, header="date,store,sales")


def test_multi_series_summaries_are_listed_worst_first(ws):
    spec = {
        "a_fine": daily_rows(60),
        "b_short": daily_rows(5),
        "c_flat": daily_rows(60, value=lambda i: 7),
    }
    report = build_quality_report(mapped(ws, multi_csv(spec), series_id="store"))
    found = codes(report)
    assert found["series_too_short"]["severity"] == "warning"  # not every series is too short
    assert found["series_too_short"]["counts"] == {"series": 1, "of": 3, "minimum": 10}
    assert found["series_too_short"]["sample"] == [{"series": "b_short", "observations": 5}]
    assert found["constant_series"]["counts"] == {"series": 1}
    assert "series_short" not in found
    series = report["series"]
    assert [i["series"] for i in series["items"]] == ["b_short", "c_flat", "a_fine"]
    assert [i["severity"] for i in series["items"]] == ["error", "warning", "info"]
    assert series["aggregate"] == {"with_errors": 1, "with_warnings": 1, "clean": 1}
    assert series["truncated"] is False and series["total"] == 3
    assert report["overview"]["series"] == 3
    assert report["overview"]["frequencies"] == {"daily": 3}
    assert report["severity"] == "warning"


def test_every_series_too_short_is_an_error_that_blocks(ws):
    spec = {"a": daily_rows(6), "b": daily_rows(8)}
    report = build_quality_report(mapped(ws, multi_csv(spec), series_id="store"))
    assert codes(report)["series_too_short"]["severity"] == "error"
    assert report["severity"] == "error"
    assert "fewer than 10" in blocking_reason(report)


def test_short_series_between_the_two_limits_is_a_warning(ws):
    report = build_quality_report(mapped(ws, csv_of(daily_rows(30))))
    assert codes(report)["series_short"]["counts"] == {"series": 1, "minimum": 50}
    assert "series_too_short" not in codes(report)
    assert report["severity"] == "warning"


def test_the_length_limits_come_from_settings(ws, settings):
    settings.DATASET_MIN_OBSERVATIONS_ERROR = 40
    settings.DATASET_MIN_OBSERVATIONS_WARN = 60
    report = build_quality_report(mapped(ws, csv_of(daily_rows(30))))
    assert codes(report)["series_too_short"]["severity"] == "error"


def test_near_constant_series(ws):
    report = build_quality_report(
        mapped(ws, csv_of(daily_rows(100, value=lambda i: 9 if i % 25 == 0 else 5)))
    )
    found = codes(report)
    assert found["near_constant_series"]["counts"] == {"series": 1}
    assert "constant_series" not in found


@pytest.mark.parametrize(
    ("freq_rows", "label"),
    [
        ([(f"2024-01-01 {h:02d}:00:00", 100 + h) for h in range(24)], "hourly"),
        ([(f"2024-{m:02d}-01", 50 + m) for m in range(1, 12)], "monthly"),
    ],
)
def test_fewer_than_two_seasonal_cycles_is_info(ws, freq_rows, label):
    report = build_quality_report(mapped(ws, csv_of(freq_rows)))
    found = codes(report)["under_two_seasons"]
    assert found["severity"] == "info"
    assert found["sample"][0]["frequency"] == label


def test_no_seasonal_note_with_two_full_cycles(ws):
    rows = daily_rows(20)  # 20 daily values >= 2 weeks
    assert "under_two_seasons" not in codes(build_quality_report(mapped(ws, csv_of(rows))))


def test_yearly_series_has_no_seasonal_note(ws):
    rows = [(f"{2000 + i}-01-01", 10 + i) for i in range(11)]
    assert "under_two_seasons" not in codes(build_quality_report(mapped(ws, csv_of(rows))))


def test_majority_negative_targets_are_not_flagged(ws):
    rows = daily_rows(60, value=lambda i: -(1 + i % 9))
    assert "unusual_negatives" not in codes(build_quality_report(mapped(ws, csv_of(rows))))


def test_empty_series_ids_are_a_warning(ws):
    rows = [(day(i), "" if i < 3 else "x", 10 + i % 4) for i in range(60)]
    report = build_quality_report(mapped(ws, csv_of(rows, "date,store,sales"), series_id="store"))
    assert codes(report)["missing_series_id"]["counts"] == {"rows": 3}


# --- truncation ----------------------------------------------------------------------------


def test_series_summaries_are_truncated_at_fifty_worst_first(ws):
    spec = {f"s{i:02d}": daily_rows(12) for i in range(60)}
    spec["zz_tiny"] = daily_rows(4)
    report = build_quality_report(mapped(ws, multi_csv(spec), series_id="store"))
    series = report["series"]
    assert series["total"] == 61 and series["listed"] == 50 and series["truncated"] is True
    assert len(series["items"]) == 50
    assert series["items"][0]["series"] == "zz_tiny" and series["items"][0]["severity"] == "error"
    assert series["aggregate"] == {"with_errors": 1, "with_warnings": 60, "clean": 0}
    note = codes(report)["series_summaries_truncated"]
    assert note["severity"] == "info" and note["counts"] == {"series": 61, "listed": 50}
    # findings still count every series, not just the listed ones
    assert codes(report)["series_short"]["counts"]["series"] == 60


def test_exactly_fifty_series_are_not_truncated(ws):
    spec = {f"s{i:02d}": daily_rows(12) for i in range(50)}
    report = build_quality_report(mapped(ws, multi_csv(spec), series_id="store"))
    assert report["series"]["truncated"] is False
    assert "series_summaries_truncated" not in codes(report)


# --- engine edge cases ---------------------------------------------------------------------


def frame_of(values):
    return pd.DataFrame(
        {
            "ts": pd.to_datetime([day(i) for i in range(len(values))]),
            "series": [""] * len(values),
            "target": values,
            "line": np.arange(2, len(values) + 2),
        }
    )


MAPPING = {"target": "y", "date": "d", "series_id": None, "regressors": []}


def loaded_of(values):
    state = NumericState(".")
    state.empty = int(np.isnan(values).sum())
    state.converted = len(values) - state.empty
    return Loaded(frame_of(values), 2, state, {}, 0)


def test_a_target_without_any_number_is_an_error():
    report = build_report(loaded_of([np.nan] * 30), MAPPING, {})
    found = codes(report)
    assert found["target_not_numeric"]["severity"] == "error"
    assert report["severity"] == "error"
    assert "no numeric values" in blocking_reason(report)


def test_outlier_rules_skip_series_without_a_spread():
    flat_with_one_jump = [5.0] * 29 + [500.0]  # IQR = 0 and MAD = 0: nothing to measure against
    report = build_report(loaded_of(flat_with_one_jump), MAPPING, {})
    assert "outliers_iqr" not in codes(report) and "outliers_robust_z" not in codes(report)
    assert "near_constant_series" in codes(report)


def test_outliers_need_a_minimum_number_of_points():
    report = build_report(loaded_of([1.0, 2, 3, 2, 1, 900]), MAPPING, {})
    assert "outliers_iqr" not in codes(report)


def test_building_a_report_without_a_mapping_fails_cleanly(ws):
    dataset = make_dataset(ws, csv_of(daily_rows(20)))
    with pytest.raises(QualityReportError, match="no column mapping"):
        build_quality_report(dataset)


def test_a_missing_file_raises_file_not_found(ws):
    dataset = mapped(ws, csv_of(daily_rows(20)))
    dataset.file.storage.delete(dataset.file.name)
    with pytest.raises(FileNotFoundError):
        build_quality_report(dataset)
