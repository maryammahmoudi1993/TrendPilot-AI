from datetime import datetime, timedelta

import pandas as pd
import pytest

from apps.datasets.frequency import detect_frequency


def stamps(start, step, count, skip=()):
    out, current = [], start
    for i in range(count):
        if i not in skip:
            out.append(current)
        current = step(current)
    return pd.Series(pd.to_datetime(out))


def every(**kwargs):
    return lambda current: current + timedelta(**kwargs)


def add_months(months):
    def step(current):
        total = current.year * 12 + current.month - 1 + months
        return current.replace(year=total // 12, month=total % 12 + 1)

    return step


START = datetime(2024, 1, 1)


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (every(minutes=1), "1min"),
        (every(minutes=15), "15min"),
        (every(hours=1), "hourly"),
        (every(hours=6), "6h"),
        (every(days=1), "daily"),
        (every(days=7), "weekly"),
        (every(days=14), "14D"),
        (add_months(1), "monthly"),
        (add_months(3), "quarterly"),
        (add_months(12), "yearly"),
    ],
)
def test_regular_series_get_the_expected_label(step, expected):
    result = detect_frequency(stamps(START, step, 40))
    assert result.frequency == expected
    assert result.regular and result.missing_periods == 0 and result.duplicates == 0


def test_month_end_dates_are_monthly():
    month_ends = pd.Series(pd.date_range("2023-01-31", periods=24, freq="ME"))
    assert detect_frequency(month_ends).frequency == "monthly"


def test_unsorted_input_gives_the_same_answer():
    shuffled = stamps(START, every(days=1), 30).sample(frac=1, random_state=3)
    assert detect_frequency(shuffled).frequency == "daily"


def test_gaps_are_counted_and_the_first_few_listed():
    result = detect_frequency(stamps(START, every(days=1), 60, skip={10, 11, 30}))
    assert result.frequency == "daily" and result.regular
    assert result.missing_periods == 3
    assert result.gaps[0] == {"after": "2024-01-10T00:00:00", "missing": 2}
    assert result.gaps[1] == {"after": "2024-01-30T00:00:00", "missing": 1}


def test_at_most_five_gaps_are_listed_but_all_are_counted():
    result = detect_frequency(stamps(START, every(days=1), 100, skip=set(range(5, 95, 3))))
    assert len(result.gaps) == 5 and result.missing_periods == 30


def test_duplicate_timestamps_are_counted_not_used_as_a_period():
    base = stamps(START, every(days=1), 20)
    result = detect_frequency(pd.concat([base, base.iloc[:4]], ignore_index=True))
    assert result.frequency == "daily" and result.duplicates == 4


def test_irregular_spacing_is_reported_as_irregular():
    offsets = [0, 1, 5, 6, 14, 15, 29, 31, 60, 61, 100, 130, 131, 200]
    series = pd.Series(pd.to_datetime([START + timedelta(days=d) for d in offsets]))
    result = detect_frequency(series)
    assert result.frequency == "irregular" and not result.regular


def test_too_few_points_is_unknown():
    result = detect_frequency(stamps(START, every(days=1), 2))
    assert result.frequency == "unknown" and not result.regular


def test_monthly_with_a_missing_month_keeps_the_label_and_counts_the_gap():
    result = detect_frequency(stamps(START, add_months(1), 30, skip={7}))
    assert result.frequency == "monthly" and result.missing_periods == 1


def test_series_are_judged_one_by_one_not_pooled():
    # Two series that are each daily; pooled, the timestamps would look like duplicates.
    days = stamps(START, every(days=1), 30)
    stamps_all = pd.concat([days, days], ignore_index=True)
    ids = ["a"] * 30 + ["b"] * 30
    result = detect_frequency(stamps_all, ids)
    assert result.frequency == "daily" and result.series_count == 2
    assert result.duplicates == 0 and result.consistent


def test_series_with_different_frequencies_are_mixed():
    daily = stamps(START, every(days=1), 30)
    weekly = stamps(START, every(days=7), 30)
    result = detect_frequency(
        pd.concat([daily, weekly], ignore_index=True), ["a"] * 30 + ["b"] * 30
    )
    assert result.frequency == "mixed" and not result.consistent
    assert result.by_series == {"a": "daily", "b": "weekly"}


def test_a_short_series_does_not_break_an_otherwise_consistent_dataset():
    daily = stamps(START, every(days=1), 30)
    result = detect_frequency(
        pd.concat([daily, daily.iloc[:2]], ignore_index=True), ["a"] * 30 + ["b"] * 2
    )
    assert result.frequency == "daily" and result.consistent
    assert result.short_series == 1


def test_as_dict_is_json_serialisable():
    import json

    result = detect_frequency(stamps(START, every(days=1), 20, skip={5}))
    assert json.loads(json.dumps(result.as_dict()))["frequency"] == "daily"
