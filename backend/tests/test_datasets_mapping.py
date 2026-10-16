import csv
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditAction, AuditEvent
from apps.datasets.columns import read_columns
from apps.datasets.models import Dataset, DatasetStatus

pytestmark = pytest.mark.django_db


def upload(client, workspace, content: str, name="data.csv"):
    file = SimpleUploadedFile(name, content.encode(), content_type="text/csv")
    response = client.post(
        f"/api/workspaces/{workspace.pk}/datasets/", {"file": file}, format="multipart"
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def mapping_url(workspace, dataset_id):
    return f"/api/workspaces/{workspace.pk}/datasets/{dataset_id}/mapping/"


@pytest.fixture
def ctx(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    return {"ws": ws, "owner": client_for(two_workspaces["a"]["owner"]), "users": two_workspaces}


def put_mapping(ctx, csv_text, body, method="put"):
    dataset_id = upload(ctx["owner"], ctx["ws"], csv_text)
    url = mapping_url(ctx["ws"], dataset_id)
    return dataset_id, getattr(ctx["owner"], method)(url, body, format="json")


def problems(response):
    assert response.status_code == 400, response.content
    return response.json()["error"]["details"]


ISO_CSV = "date,sales,store,temp\n2024-01-01,10,a,1.5\n2024-01-02,12,a,2.5\n2024-01-03,11,b,3\n"


def test_iso_dates_and_numeric_target_are_saved(ctx):
    body = {"date": "date", "target": "sales", "series_id": "store", "regressors": ["temp"]}
    dataset_id, response = put_mapping(ctx, ISO_CSV, body)
    assert response.status_code == 200, response.content
    mapping = response.json()["column_mapping"]
    assert mapping["date"] == "date" and mapping["series_id"] == "store"
    assert mapping["regressors"] == ["temp"]
    assert mapping["date_format"] == "%Y-%m-%d"
    assert mapping["parsing"]["date"]["parsed"] == 3
    assert mapping["parsing"]["target"]["converted"] == 3
    assert mapping["parsing"]["regressors"]["temp"]["converted"] == 3
    assert Dataset.objects.get(pk=dataset_id).column_mapping == mapping


def test_mapping_change_writes_an_audit_event_with_before_and_after(ctx):
    dataset_id, _ = put_mapping(ctx, ISO_CSV, {"date": "date", "target": "sales"})
    ctx["owner"].patch(mapping_url(ctx["ws"], dataset_id), {"target": "temp"}, format="json")
    events = AuditEvent.objects.filter(action=AuditAction.DATASET_MAPPING).order_by("created_at")
    assert events.count() == 2
    second = events.last()
    assert second.workspace == ctx["ws"] and second.target_id == dataset_id
    assert second.metadata["before"]["target"] == "sales"
    assert second.metadata["after"]["target"] == "temp"
    assert second.actor == ctx["users"]["a"]["owner"]


def test_patch_merges_and_put_replaces(ctx):
    dataset_id, _ = put_mapping(
        ctx, ISO_CSV, {"date": "date", "target": "sales", "regressors": ["temp"]}
    )
    url = mapping_url(ctx["ws"], dataset_id)
    merged = ctx["owner"].patch(url, {"series_id": "store"}, format="json").json()
    assert merged["column_mapping"]["regressors"] == ["temp"]
    assert merged["column_mapping"]["series_id"] == "store"
    replaced = ctx["owner"].put(url, {"date": "date", "target": "sales"}, format="json").json()
    assert replaced["column_mapping"]["regressors"] == []
    assert replaced["column_mapping"]["series_id"] is None


def test_put_requires_date_and_target(ctx):
    _, response = put_mapping(ctx, ISO_CSV, {"date": "date"})
    assert response.status_code == 400
    assert "target" in problems(response)


def test_patch_without_an_existing_mapping_requires_date_and_target(ctx):
    _, response = put_mapping(ctx, ISO_CSV, {"series_id": "store"}, method="patch")
    assert set(problems(response)) == {"date", "target"}


def test_us_eu_ambiguity_is_reported_and_resolved_by_date_order(ctx):
    csv_text = "d,v\n01/02/2024,1\n03/04/2024,2\n05/06/2024,3\n"
    dataset_id, response = put_mapping(ctx, csv_text, {"date": "d", "target": "v"})
    date = problems(response)["date"]
    assert date["code"] == "ambiguous_date_order"
    assert date["candidate_orders"] == ["dmy", "mdy"]

    url = mapping_url(ctx["ws"], dataset_id)
    ok = ctx["owner"].put(url, {"date": "d", "target": "v", "date_order": "dmy"}, format="json")
    assert ok.status_code == 200
    assert ok.json()["column_mapping"]["parsing"]["date"]["earliest"].startswith("2024-02-01")


def test_day_above_twelve_settles_the_order_without_a_hint(ctx):
    csv_text = "d,v\n13/01/2024,1\n02/02/2024,2\n"
    _, response = put_mapping(ctx, csv_text, {"date": "d", "target": "v"})
    assert response.status_code == 200
    assert response.json()["column_mapping"]["parsing"]["date"]["order"] == "dmy"


def test_mixed_date_formats_are_rejected_with_count_and_examples(ctx):
    csv_text = "d,v\n2024-01-01,1\n03/01/2024,2\n2024-01-03,3\n15/02/2024,4\n"
    _, response = put_mapping(ctx, csv_text, {"date": "d", "target": "v"})
    date = problems(response)["date"]
    assert date["code"] == "mixed_date_formats"
    assert date["bad_count"] == 2
    assert date["examples"] == ["03/01/2024", "15/02/2024"]


def test_unparseable_dates_report_count_and_first_examples(ctx):
    rows = "\n".join(f"oops{i},{i}" for i in range(7))
    _, response = put_mapping(ctx, f"d,v\n2024-01-01,1\n{rows}\n", {"date": "d", "target": "v"})
    date = problems(response)["date"]
    assert date["code"] == "unparseable_dates"
    assert date["bad_count"] == 7
    assert date["examples"] == [f"oops{i}" for i in range(5)]


def test_utc_offsets_and_timezone_hint(ctx):
    aware = "d,v\n2024-01-01T10:00:00Z,1\n2024-01-01T11:00:00+02:00,2\n"
    _, response = put_mapping(ctx, aware, {"date": "d", "target": "v"})
    assert response.json()["column_mapping"]["parsing"]["date"]["has_utc_offset"] is True

    naive = "d,v\n2024-06-01 10:00,1\n2024-06-01 11:00,2\n"
    body = {"date": "d", "target": "v", "timezone": "Europe/Berlin"}
    _, response = put_mapping(ctx, naive, body)
    parsing = response.json()["column_mapping"]["parsing"]["date"]
    assert parsing["timezone"] == "Europe/Berlin" and parsing["has_utc_offset"] is False


def test_unknown_timezone_is_rejected(ctx):
    body = {"date": "date", "target": "sales", "timezone": "Mars/Olympus"}
    _, response = put_mapping(ctx, ISO_CSV, body)
    assert "timezone" in problems(response)


def test_thousand_separators_in_the_target(ctx):
    csv_text = 'date,sales\n2024-01-01,"1,200.50"\n2024-01-02,"1,300"\n2024-01-03,950\n'
    _, response = put_mapping(ctx, csv_text, {"date": "date", "target": "sales"})
    target = response.json()["column_mapping"]["parsing"]["target"]
    assert (target["converted"], target["failed"], target["decimal_separator"]) == (3, 0, ".")


def test_decimal_commas_with_semicolon_delimiter(ctx):
    csv_text = "datum;umsatz\n2024-01-01;1.234,5\n2024-01-02;99,25\n2024-01-03;1.000\n"
    _, response = put_mapping(ctx, csv_text, {"date": "datum", "target": "umsatz"})
    target = response.json()["column_mapping"]["parsing"]["target"]
    assert target["decimal_separator"] == ","
    assert target["converted"] == 3


def test_ambiguous_decimal_separator_is_reported_and_overridable(ctx):
    csv_text = 'date,sales\n2024-01-01,"1,234"\n2024-01-02,"5,678"\n'
    dataset_id, response = put_mapping(ctx, csv_text, {"date": "date", "target": "sales"})
    assert response.json()["column_mapping"]["parsing"]["target"]["ambiguous_separator"] is True
    body = {"date": "date", "target": "sales", "decimal_separator": ","}
    again = ctx["owner"].put(mapping_url(ctx["ws"], dataset_id), body, format="json")
    assert again.json()["column_mapping"]["parsing"]["target"]["ambiguous_separator"] is False


def _target_csv(total: int, bad_rows: int) -> str:
    """``total`` daily rows; the first ``bad_rows`` have an unconvertible target."""
    rows = []
    for i in range(total):
        day = date(2024, 1, 1) + timedelta(days=i)
        rows.append(f"{day.isoformat()},{'n/a?' if i < bad_rows else i}\n")
    return "date,sales\n" + "".join(rows)


def test_target_just_above_the_target_threshold_is_accepted(ctx):
    # 1 failure in 100 non-empty cells = 99%, exactly the default target bar.
    _, response = put_mapping(ctx, _target_csv(100, 1), {"date": "date", "target": "sales"})
    assert response.status_code == 200, response.content
    target = response.json()["column_mapping"]["parsing"]["target"]
    assert target["failed"] == 1 and target["failed_examples"] == ["n/a?"]


def _two_column_csv(total: int, bad_in: str) -> str:
    """Daily ``sales`` and ``temp`` columns; ``bad_in`` gets one unconvertible cell."""
    rows = []
    for i in range(total):
        day = (date(2024, 1, 1) + timedelta(days=i)).isoformat()
        sales = "n/a?" if bad_in == "sales" and i == 0 else i
        temp = "n/a?" if bad_in == "temp" and i == 0 else i
        rows.append(f"{day},{sales},{temp}\n")
    return "date,sales,temp\n" + "".join(rows)


def test_98_percent_is_too_lossy_for_the_target(ctx):
    # 1 failure in 50 non-empty cells = 98%, below the 99% target bar.
    _, response = put_mapping(
        ctx, _two_column_csv(50, "sales"), {"date": "date", "target": "sales"}
    )
    assert problems(response)["target"]["code"] == "target_not_numeric"


def test_98_percent_is_fine_for_a_regressor(ctx):
    body = {"date": "date", "target": "sales", "regressors": ["temp"]}
    _, response = put_mapping(ctx, _two_column_csv(50, "temp"), body)
    assert response.status_code == 200, response.content
    assert response.json()["column_mapping"]["parsing"]["regressors"]["temp"]["failed"] == 1


def test_target_threshold_is_its_own_setting(ctx, settings):
    settings.DATASET_MIN_TARGET_NUMERIC_SHARE = 0.9
    _, response = put_mapping(ctx, _target_csv(50, 1), {"date": "date", "target": "sales"})
    assert response.status_code == 200, response.content
    settings.DATASET_MIN_TARGET_NUMERIC_SHARE = 1.0
    _, response = put_mapping(ctx, _target_csv(100, 1), {"date": "date", "target": "sales"})
    assert problems(response)["target"]["code"] == "target_not_numeric"


def test_regressor_threshold_is_unchanged_and_independent(ctx, settings):
    settings.DATASET_MIN_NUMERIC_SHARE = 1.0
    body = {"date": "date", "target": "sales", "regressors": ["temp"]}
    _, response = put_mapping(ctx, _two_column_csv(100, "temp"), body)
    assert problems(response)["regressors"]["temp"]["code"] == "regressor_not_numeric"


def test_failed_cells_stay_in_the_parse_result_as_missing_with_their_line_numbers(ctx):
    csv_text = _target_csv(300, 2)
    _, response = put_mapping(ctx, csv_text, {"date": "date", "target": "sales"})
    target = response.json()["column_mapping"]["parsing"]["target"]
    assert target["failed"] == 2 and target["empty"] == 0
    assert target["missing"] == 2  # failed cells are kept as missing, never dropped
    assert target["failed_lines"] == [2, 3]  # file line numbers, header is line 1
    assert response.json()["row_count"] == 300


def test_non_numeric_target_is_rejected(ctx):
    csv_text = "date,label\n2024-01-01,high\n2024-01-02,low\n"
    _, response = put_mapping(ctx, csv_text, {"date": "date", "target": "label"})
    assert problems(response)["target"]["code"] == "target_not_numeric"


def test_mostly_non_numeric_target_reports_failed_count_and_examples(ctx):
    csv_text = "date,v\n2024-01-01,1\n2024-01-02,x\n2024-01-03,y\n2024-01-04,2\n"
    _, response = put_mapping(ctx, csv_text, {"date": "date", "target": "v"})
    target = problems(response)["target"]
    assert target["failed"] == 2 and target["examples"] == ["x", "y"]


def test_non_numeric_regressor_is_rejected_by_name(ctx):
    body = {"date": "date", "target": "sales", "regressors": ["store"]}
    _, response = put_mapping(ctx, ISO_CSV, body)
    assert problems(response)["regressors"]["store"]["code"] == "regressor_not_numeric"


def test_missing_column_lists_the_available_ones(ctx):
    _, response = put_mapping(ctx, ISO_CSV, {"date": "when", "target": "sales"})
    date = problems(response)["date"]
    assert date["code"] == "column_not_found"
    assert date["available_columns"] == ["date", "sales", "store", "temp"]


def test_same_column_cannot_serve_two_roles(ctx):
    body = {"date": "date", "target": "sales", "series_id": "sales"}
    _, response = put_mapping(ctx, ISO_CSV, body)
    found = problems(response)
    assert found["target"]["code"] == found["series_id"]["code"] == "duplicate_role"


def test_the_same_regressor_cannot_be_listed_twice(ctx):
    body = {"date": "date", "target": "sales", "regressors": ["temp", "temp"]}
    _, response = put_mapping(ctx, ISO_CSV, body)
    assert problems(response)["regressors"]["code"] == "duplicate_role"


def test_a_rejected_mapping_saves_nothing_and_writes_no_audit_event(ctx):
    dataset_id, response = put_mapping(ctx, ISO_CSV, {"date": "nope", "target": "sales"})
    assert response.status_code == 400
    assert Dataset.objects.get(pk=dataset_id).column_mapping == {}
    assert not AuditEvent.objects.filter(action=AuditAction.DATASET_MAPPING).exists()


def test_changing_the_mapping_resets_derived_state(ctx):
    dataset_id, _ = put_mapping(ctx, ISO_CSV, {"date": "date", "target": "sales"})
    Dataset.objects.filter(pk=dataset_id).update(
        status=DatasetStatus.VALIDATED, detected_frequency="daily"
    )
    ctx["owner"].patch(mapping_url(ctx["ws"], dataset_id), {"target": "temp"}, format="json")
    dataset = Dataset.objects.get(pk=dataset_id)
    assert dataset.status == DatasetStatus.UPLOADED
    assert dataset.detected_frequency == "daily"  # recomputed from the new mapping


def daily_csv(days=30, skip=(), dup_last=False):
    rows = [
        f"{(date(2024, 1, 1) + timedelta(days=i)).isoformat()},{i}\n"
        for i in range(days)
        if i not in skip
    ]
    if dup_last:
        rows.append(rows[-1])
    return "date,sales\n" + "".join(rows)


def test_frequency_is_detected_and_stored_with_the_mapping(ctx):
    dataset_id, response = put_mapping(
        ctx, daily_csv(30, skip={4, 5}, dup_last=True), {"date": "date", "target": "sales"}
    )
    body = response.json()
    assert body["detected_frequency"] == "daily"
    frequency = body["column_mapping"]["parsing"]["frequency"]
    assert frequency["frequency"] == "daily" and frequency["regular"]
    assert frequency["missing_periods"] == 2 and frequency["duplicates"] == 1
    assert frequency["gaps"][0]["missing"] == 2
    assert Dataset.objects.get(pk=dataset_id).detected_frequency == "daily"


def test_frequency_is_judged_per_series(ctx):
    rows = "".join(f"2024-01-{d:02d},a,{d}\n2024-01-{d:02d},b,{d}\n" for d in range(1, 21))
    _, response = put_mapping(
        ctx, "date,store,sales\n" + rows, {"date": "date", "target": "sales", "series_id": "store"}
    )
    frequency = response.json()["column_mapping"]["parsing"]["frequency"]
    assert frequency["frequency"] == "daily" and frequency["series_count"] == 2
    assert frequency["duplicates"] == 0


def test_monthly_text_dates_with_a_utc_offset(ctx):
    rows = "".join(f"2024-{m:02d}-01 00:00:00+02:00,{m}\n" for m in range(1, 13))
    _, response = put_mapping(ctx, "date,sales\n" + rows, {"date": "date", "target": "sales"})
    assert response.json()["detected_frequency"] == "monthly"


def test_irregular_dates_are_stored_as_irregular_not_rejected(ctx):
    days = [1, 2, 9, 10, 25, 26, 27, 28]
    rows = "".join(f"2024-01-{d:02d},{d}\n" for d in days) + "2024-03-15,1\n2024-06-30,2\n"
    _, response = put_mapping(ctx, "date,sales\n" + rows, {"date": "date", "target": "sales"})
    assert response.status_code == 200, response.content
    assert response.json()["detected_frequency"] == "irregular"


def test_dataset_without_a_stored_file_gives_409(ctx):
    dataset = Dataset.objects.create(
        workspace=ctx["ws"], name="x", original_filename="x.csv", size=1, sha256="0" * 64
    )
    response = ctx["owner"].put(
        mapping_url(ctx["ws"], dataset.pk), {"date": "a", "target": "b"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_unavailable"


def test_analyst_may_map_viewer_and_outsiders_may_not(ctx, client_for):
    dataset_id = upload(ctx["owner"], ctx["ws"], ISO_CSV)
    url = mapping_url(ctx["ws"], dataset_id)
    body = {"date": "date", "target": "sales"}
    users = ctx["users"]
    assert client_for(users["a"]["analyst"]).put(url, body, format="json").status_code == 200
    assert client_for(users["a"]["viewer"]).put(url, body, format="json").status_code == 403
    assert client_for(users["a"]["viewer"]).patch(url, body, format="json").status_code == 403
    assert client_for(users["b"]["owner"]).put(url, body, format="json").status_code == 404
    assert client_for(users["outsider"]).patch(url, body, format="json").status_code == 404
    assert client_for().put(url, body, format="json").status_code == 401


def test_other_workspaces_dataset_id_is_404_through_own_workspace(ctx, client_for):
    dataset_id = upload(ctx["owner"], ctx["ws"], ISO_CSV)
    other = ctx["users"]["b"]
    url = mapping_url(other["workspace"], dataset_id)
    response = client_for(other["owner"]).put(
        url, {"date": "date", "target": "sales"}, format="json"
    )
    assert response.status_code == 404


def test_read_columns_handles_bom_and_skips_unknown_names(ctx):
    dataset_id = upload(ctx["owner"], ctx["ws"], "﻿a,b,c\n1,2,3\n7,8,9\n")
    header, columns = read_columns(Dataset.objects.get(pk=dataset_id), ["a", "c", "zz"])
    assert header == ["a", "b", "c"]
    assert columns == {"a": ["1", "7"], "c": ["3", "9"]}


def test_read_columns_pads_short_rows(ctx, monkeypatch):
    # The upload sniffer rejects ragged files today; the reader still must not crash on one.
    dataset_id = upload(ctx["owner"], ctx["ws"], "a,b,c\n1,2,3\n7,8,9\n")
    dataset = Dataset.objects.get(pk=dataset_id)
    with dataset.file.open("wb") as handle:
        handle.write(b"a,b,c\n1,2,3\n4,5\n")
    monkeypatch.setattr("apps.datasets.columns.detect_dialect", lambda text: csv.excel)
    _, columns = read_columns(dataset, ["c"])
    assert columns == {"c": ["3", ""]}
