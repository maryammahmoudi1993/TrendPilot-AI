import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.datasets.models import Dataset, DatasetStatus

pytestmark = pytest.mark.django_db


def csv_file(name="sales.csv", content=b"date,value\n2024-01-01,1\n2024-01-02,2\n"):
    return SimpleUploadedFile(name, content, content_type="text/csv")


def test_owner_can_upload_a_valid_csv(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == DatasetStatus.UPLOADED
    assert body["row_count"] == 2
    assert body["name"] == "sales.csv"
    assert "file" not in body

    dataset = Dataset.objects.get(pk=body["id"])
    assert dataset.original_filename == "sales.csv"
    assert "sales" not in dataset.file.name  # stored name never derives from the client's


def test_analyst_can_upload(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["analyst"]).post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert response.status_code == 201, response.content


def test_custom_name_overrides_filename(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(), "name": "Q1 sales"},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    assert response.json()["name"] == "Q1 sales"


def test_empty_file_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file(content=b"")}, format="multipart"
    )
    assert response.status_code == 400
    assert "empty" in response.json()["error"]["details"]["file"][0]


def test_oversize_file_rejected(two_workspaces, client_for, settings):
    settings.DATASET_MAX_UPLOAD_BYTES = 10
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert response.status_code == 400
    assert "exceeds" in response.json()["error"]["details"]["file"][0]


def test_too_many_rows_rejected(two_workspaces, client_for, settings):
    settings.DATASET_MAX_ROWS = 1
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert response.status_code == 400
    assert "more than" in response.json()["error"]["details"]["file"][0]


def test_binary_file_renamed_to_csv_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    binary = bytes(range(256))
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=binary)},
        format="multipart",
    )
    assert response.status_code == 400
    assert "binary" in response.json()["error"]["details"]["file"][0]


def test_wrong_delimiter_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=b"date|value\n2024-01-01|1\n2024-01-02|2\n")},
        format="multipart",
    )
    assert response.status_code == 400
    assert "delimiter" in response.json()["error"]["details"]["file"][0]


def test_bom_csv_is_accepted(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    content = "﻿date,value\n2024-01-01,1\n".encode()
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=content)},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    assert response.json()["row_count"] == 1


def test_non_csv_extension_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(name="sales.txt")},
        format="multipart",
    )
    assert response.status_code == 400
    assert ".csv" in response.json()["error"]["details"]["file"][0]


def test_duplicate_upload_in_same_workspace_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    client = client_for(two_workspaces["a"]["owner"])
    first = client.post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert first.status_code == 201, first.content

    second = client.post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(name="again.csv")},
        format="multipart",
    )
    assert second.status_code == 400
    assert "already been uploaded" in second.json()["error"]["details"]["file"][0]
    assert Dataset.objects.filter(workspace=ws).count() == 1


def test_same_content_allowed_in_a_different_workspace(two_workspaces, client_for):
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{a.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    response = client_for(two_workspaces["b"]["owner"]).post(
        f"/api/workspaces/{b.pk}/datasets/", {"file": csv_file()}, format="multipart"
    )
    assert response.status_code == 201, response.content


def test_sha256_is_computed_correctly(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    content = b"date,value\n2024-01-01,1\n2024-01-02,2\n"
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=content)},
        format="multipart",
    )
    assert response.json()["sha256"] == hashlib.sha256(content).hexdigest()


def test_list_and_retrieve_show_the_dataset(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    client = client_for(two_workspaces["a"]["owner"])
    created = client.post(
        f"/api/workspaces/{ws.pk}/datasets/", {"file": csv_file()}, format="multipart"
    ).json()

    listed = client.get(f"/api/workspaces/{ws.pk}/datasets/").json()
    assert [row["id"] for row in listed["results"]] == [created["id"]]

    detail = client.get(f"/api/workspaces/{ws.pk}/datasets/{created['id']}/").json()
    assert detail["id"] == created["id"]
    assert "file" not in detail


def test_upload_with_a_trailing_short_row_is_accepted_and_the_report_is_stored(
    two_workspaces, client_for
):
    ws = two_workspaces["a"]["workspace"]
    content = b"date,value,store\n2024-01-01,1,a\n2024-01-02,2,a\n2024-01-03,3\n"
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=content)},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["row_count"] == 3
    assert body["upload_report"]["delimiter"] == ","
    assert body["upload_report"]["ragged"] == {"count": 1, "short": 1, "long": 0, "lines": [4]}
    assert Dataset.objects.get(pk=body["id"]).upload_report == body["upload_report"]


def test_upload_with_half_the_rows_ragged_is_rejected(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    content = b"date,value,store\n" + b"2024-01-01,1,a\n2024-01-02,2\n" * 5
    response = client_for(two_workspaces["a"]["owner"]).post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=content)},
        format="multipart",
    )
    assert response.status_code == 400
    assert "same number of fields" in response.json()["error"]["details"]["file"][0]
    assert Dataset.objects.count() == 0


def test_a_ragged_upload_can_still_be_mapped(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    client = client_for(two_workspaces["a"]["owner"])
    content = b"date,value,store\n2024-01-01,1,a\n2024-01-02,2,a\n2024-01-03,3\n"
    dataset_id = client.post(
        f"/api/workspaces/{ws.pk}/datasets/",
        {"file": csv_file(content=content)},
        format="multipart",
    ).json()["id"]
    response = client.put(
        f"/api/workspaces/{ws.pk}/datasets/{dataset_id}/mapping/",
        {"date": "date", "target": "value", "series_id": "store"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["column_mapping"]["parsing"]["target"]["converted"] == 3
