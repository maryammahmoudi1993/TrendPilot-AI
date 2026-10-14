from django.core.files.base import ContentFile
from django.db import transaction

from .models import Dataset


@transaction.atomic
def upload_dataset(
    *,
    workspace,
    actor,
    original_filename: str,
    raw: bytes,
    sha256: str,
    row_count: int,
    name: str,
) -> Dataset:
    """Persist a validated upload: store the file under a random name and save the row."""
    dataset = Dataset(
        workspace=workspace,
        name=name,
        original_filename=original_filename,
        size=len(raw),
        sha256=sha256,
        row_count=row_count,
        created_by=actor,
    )
    dataset.file.save(original_filename, ContentFile(raw), save=False)
    dataset.save()
    return dataset
