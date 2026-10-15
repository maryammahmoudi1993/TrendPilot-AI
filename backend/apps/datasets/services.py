from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditAction
from apps.audit.services import record

from .mapping import OPTION_KEYS, ROLE_KEYS, resolve_mapping
from .models import Dataset, DatasetStatus


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


def _settings_of(mapping: dict) -> dict:
    return {key: mapping.get(key) for key in (*ROLE_KEYS, *OPTION_KEYS)}


@transaction.atomic
def update_mapping(*, dataset: Dataset, actor, data: dict, partial: bool) -> Dataset:
    """Validate and save a column mapping, reset derived state and write an audit event.

    ``partial`` merges ``data`` over the stored mapping (PATCH); otherwise ``data`` is the
    whole mapping (PUT). Nothing is saved when validation fails.
    """
    dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
    previous = _settings_of(dataset.column_mapping)
    merged = {**previous, **data} if partial else dict(data)
    if not merged.get("date") or not merged.get("target"):
        raise ValidationError(
            {
                field: ["This field is required."]
                for field in ("date", "target")
                if not merged.get(field)
            }
        )
    mapping = resolve_mapping(dataset, merged)

    dataset.column_mapping = mapping
    dataset.status = DatasetStatus.UPLOADED
    dataset.detected_frequency = ""
    dataset.save(update_fields=["column_mapping", "status", "detected_frequency", "updated_at"])
    record(
        AuditAction.DATASET_MAPPING,
        actor=actor,
        workspace=dataset.workspace,
        target_type="dataset",
        target_id=dataset.pk,
        dataset_name=dataset.name,
        before=previous,
        after=_settings_of(mapping),
    )
    return dataset
