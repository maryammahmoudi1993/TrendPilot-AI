from datetime import date, timedelta

import pytest

from apps.datasets.dates import detect_date_column, validate_timezone


def test_iso_dates():
    result = detect_date_column(["2024-01-01", "2024-01-02", "2024-02-29"])
    assert result.ok
    assert (result.format, result.order, result.aware) == ("%Y-%m-%d", "ymd", False)
    assert result.parsed == 3
    assert result.earliest.startswith("2024-01-01")
    assert result.latest.startswith("2024-02-29")


def test_iso_datetimes_with_t_and_space():
    assert detect_date_column(["2024-01-01T10:00:00", "2024-01-01T11:00:00"]).format == (
        "%Y-%m-%dT%H:%M:%S"
    )
    assert detect_date_column(["2024-01-01 10:00", "2024-01-01 11:00"]).format == "%Y-%m-%d %H:%M"


def test_monthly_year_month():
    result = detect_date_column(["2024-01", "2024-02", "2024-03"])
    assert result.ok and result.format == "%Y-%m"


def test_text_months():
    result = detect_date_column(["01 Jan 2024", "02 Jan 2024"])
    assert result.ok and result.format == "%d %b %Y"
    assert detect_date_column(["March 5, 2024", "March 6, 2024"]).ok


def test_day_first_is_proven_by_a_day_above_twelve():
    result = detect_date_column(["13/01/2024", "02/02/2024", "03/04/2024"])
    assert result.ok and result.order == "dmy"


def test_month_first_is_proven_by_a_day_above_twelve():
    result = detect_date_column(["01/13/2024", "02/02/2024", "03/04/2024"])
    assert result.ok and result.order == "mdy"


def test_us_eu_ambiguity_is_reported_not_guessed():
    result = detect_date_column(["01/02/2024", "03/04/2024", "05/06/2024"])
    assert not result.ok
    assert result.code == "ambiguous_date_order"
    assert result.candidate_orders == ["dmy", "mdy"]


@pytest.mark.parametrize(("hint", "first"), [("dmy", "01/02/2024"), ("mdy", "01/02/2024")])
def test_order_hint_resolves_ambiguity(hint, first):
    result = detect_date_column([first, "03/04/2024"], order_hint=hint)
    assert result.ok and result.order == hint
    expected_earliest = "2024-02-01" if hint == "dmy" else "2024-01-02"
    assert result.earliest.startswith(expected_earliest)


def test_hint_that_contradicts_the_data_fails_with_examples():
    result = detect_date_column(["13/01/2024", "02/02/2024"], order_hint="mdy")
    assert not result.ok
    assert result.bad_count == 1
    assert result.bad_examples == ["13/01/2024"]


def test_mixed_formats_are_rejected_with_count_and_examples():
    cells = ["2024-01-01", "2024-01-02", "03/01/2024", "2024-01-04", "15/02/2024"]
    result = detect_date_column(cells)
    assert not result.ok
    assert result.code == "mixed_date_formats"
    assert result.bad_count == 2
    assert result.bad_examples == ["03/01/2024", "15/02/2024"]


def test_unparseable_values_report_count_and_first_five():
    cells = ["2024-01-01"] + [f"bad{i}" for i in range(8)] + ["2024-01-02"]
    result = detect_date_column(cells)
    assert not result.ok
    assert result.code == "unparseable_dates"
    assert result.bad_count == 8
    assert result.bad_examples == [f"bad{i}" for i in range(5)]


def test_empty_cells_in_the_date_column_are_rejected():
    result = detect_date_column(["2024-01-01", "", "2024-01-03", " "])
    assert not result.ok
    assert result.bad_count == 2
    assert result.bad_examples == ["<empty>"]


def test_all_text_column_fails():
    result = detect_date_column(["alpha", "beta"])
    assert not result.ok and result.bad_count == 2


def test_utc_offsets_are_detected_as_aware():
    result = detect_date_column(["2024-01-01T10:00:00Z", "2024-01-01T11:00:00+02:00"])
    assert result.ok and result.aware and result.timezone is None
    assert result.format == "%Y-%m-%dT%H:%M:%S%z"


def test_naive_and_aware_values_cannot_be_mixed():
    result = detect_date_column(["2024-01-01T10:00:00Z", "2024-01-01T11:00:00"])
    assert not result.ok and result.code == "mixed_date_formats"
    assert result.bad_count == 1


def test_timezone_hint_is_kept_for_naive_values_only():
    naive = detect_date_column(["2024-06-01 10:00"], timezone="Europe/Berlin")
    assert naive.timezone == "Europe/Berlin"
    aware = detect_date_column(["2024-06-01 10:00+02:00"], timezone="Europe/Berlin")
    assert aware.aware and aware.timezone is None


def test_late_bad_value_beyond_the_sample_is_still_caught():
    start = date(2023, 1, 1)
    cells = [(start + timedelta(days=i)).isoformat() for i in range(300)] + ["not a date"]
    result = detect_date_column(cells)
    assert not result.ok and result.bad_examples == ["not a date"]


def test_validate_timezone():
    assert validate_timezone("UTC") == "UTC"
    with pytest.raises(ValueError, match="Unknown timezone"):
        validate_timezone("Mars/Olympus")
