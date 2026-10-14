import hashlib
import uuid

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from apps.datasets.models import Dataset, DatasetStatus

pytestmark = pytest.mark.django_db


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_create_dataset(two_workspaces):
    ws = two_workspaces["a"]["workspace"]
    owner = two_workspaces["a"]["owner"]
    raw = b"date,value\n2024-01-01,1\n"
    dataset = Dataset(
        workspace=ws,
        name="sales.csv",
        original_filename="sales.csv",
        size=len(raw),
        sha256=_sha256(raw),
        row_count=1,
        created_by=owner,
    )
    dataset.file.save("sales.csv", ContentFile(raw), save=False)
    dataset.save()

    assert isinstance(dataset.pk, uuid.UUID)
    assert dataset.status == DatasetStatus.UPLOADED
    assert dataset.workspace_id == ws.pk
    assert dataset.column_mapping == {}
    assert dataset.detected_frequency == ""


def test_file_is_stored_under_a_random_name_not_the_original(two_workspaces):
    ws = two_workspaces["a"]["workspace"]
    raw = b"date,value\n2024-01-01,1\n"
    dataset = Dataset(
        workspace=ws,
        name="x",
        original_filename="my secrets.csv",
        size=len(raw),
        sha256=_sha256(raw),
    )
    dataset.file.save("my secrets.csv", ContentFile(raw), save=False)

    assert "my secrets" not in dataset.file.name
    assert dataset.file.name.startswith(f"datasets/{ws.pk}/")
    assert dataset.file.name.endswith(".csv")


def test_duplicate_sha256_rejected_within_same_workspace(two_workspaces):
    ws = two_workspaces["a"]["workspace"]
    raw = b"date,value\n2024-01-01,1\n"
    Dataset.objects.create(
        workspace=ws, name="a", original_filename="a.csv", size=len(raw), sha256=_sha256(raw)
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Dataset.objects.create(
            workspace=ws, name="b", original_filename="b.csv", size=len(raw), sha256=_sha256(raw)
        )


def test_same_sha256_allowed_across_different_workspaces(two_workspaces):
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    raw = b"date,value\n2024-01-01,1\n"
    Dataset.objects.create(
        workspace=a, name="a", original_filename="a.csv", size=len(raw), sha256=_sha256(raw)
    )
    # must not raise
    Dataset.objects.create(
        workspace=b, name="b", original_filename="b.csv", size=len(raw), sha256=_sha256(raw)
    )
    assert Dataset.objects.filter(sha256=_sha256(raw)).count() == 2


def test_str_is_name(two_workspaces):
    ws = two_workspaces["a"]["workspace"]
    dataset = Dataset(
        workspace=ws, name="sales.csv", original_filename="sales.csv", size=1, sha256="x"
    )
    assert str(dataset) == "sales.csv"
