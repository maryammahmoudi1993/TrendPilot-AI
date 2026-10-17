import logging
import uuid
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from apps.audit.models import AuditAction
from apps.audit.services import record

from .mapping import OPTION_KEYS, ROLE_KEYS, resolve_mapping
from .models import Dataset, DatasetStatus
from .quality import QualityReportError, blocking_reason, build_quality_report

logger = logging.getLogger(__name__)


class NoMappingError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Save a column mapping before validating the dataset."
    default_code = "no_mapping"


class AlreadyValidatingError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This dataset is already being validated."
    default_code = "already_validating"


@transaction.atomic
def upload_dataset(
    *,
    workspace,
    actor,
    original_filename: str,
    raw: bytes,
    sha256: str,
    row_count: int,
    upload_report: dict,
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
        upload_report=upload_report,
        created_by=actor,
    )
    dataset.file.save(original_filename, ContentFile(raw), save=False)
    dataset.save()
    return dataset


def _settings_of(mapping: dict) -> dict:
    return {key: mapping.get(key) for key in (*ROLE_KEYS, *OPTION_KEYS)}


_VALIDATION_FIELDS = (
    "status",
    "quality_report",
    "validated_at",
    "validation_error",
    "validation_run",
    "updated_at",
)


def _reset_validation(dataset: Dataset) -> None:
    """Back to 'uploaded' with no report; any run still in flight is orphaned."""
    dataset.status = DatasetStatus.UPLOADED
    dataset.quality_report = None
    dataset.validated_at = None
    dataset.validation_error = ""
    dataset.validation_run = None


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
    dataset.detected_frequency = mapping["parsing"]["frequency"]["frequency"]
    _reset_validation(dataset)
    dataset.save(update_fields=[*_VALIDATION_FIELDS, "column_mapping", "detected_frequency"])
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


def _is_stale(dataset: Dataset) -> bool:
    age = timezone.now() - dataset.updated_at
    return age > timedelta(seconds=settings.DATASET_VALIDATION_STALE_SECONDS)


def start_validation(*, dataset: Dataset, actor) -> Dataset:
    """Move a mapped dataset to 'validating' and queue the report task.

    The status change happens under a row lock, so two simultaneous requests cannot both
    start a run (the second gets 409). A run that has been 'validating' longer than
    ``DATASET_VALIDATION_STALE_SECONDS`` is considered lost and may be replaced. The task
    is queued only once the transaction has committed.
    """
    from .tasks import validate_dataset

    with transaction.atomic():
        dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
        if not dataset.column_mapping.get("date") or not dataset.column_mapping.get("target"):
            raise NoMappingError()
        if dataset.status == DatasetStatus.VALIDATING and not _is_stale(dataset):
            raise AlreadyValidatingError()
        run_id = uuid.uuid4()
        _reset_validation(dataset)
        dataset.status = DatasetStatus.VALIDATING
        dataset.validation_run = run_id
        dataset.save(update_fields=_VALIDATION_FIELDS)
        record(
            AuditAction.DATASET_VALIDATE,
            actor=actor,
            workspace=dataset.workspace,
            target_type="dataset",
            target_id=dataset.pk,
            dataset_name=dataset.name,
            phase="started",
            run=str(run_id),
        )
        transaction.on_commit(lambda: validate_dataset.delay(str(dataset.pk), str(run_id)))
    return dataset


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "The dataset's file is missing from storage."
    if isinstance(exc, QualityReportError):
        return str(exc)
    if isinstance(exc, ValueError):
        return f"The dataset's file could not be read: {exc}"
    if isinstance(exc, SoftTimeLimitExceeded):
        return "Validation took too long and was stopped."
    return "Validation stopped because of an unexpected error; it was logged for the operators."


def run_validation(dataset_id: str, run_id: str) -> str:
    """Compute and store the report for one run. Safe to repeat and to run twice.

    Returns ``"validated"``, ``"failed"`` or ``"skipped"`` (the dataset is gone, no longer
    validating, or a newer run replaced this one, in which case nothing is written).
    """
    dataset = Dataset.objects.filter(
        pk=dataset_id, status=DatasetStatus.VALIDATING, validation_run=run_id
    ).first()
    if dataset is None:
        return "skipped"

    report, reason = None, ""
    try:
        report = build_quality_report(dataset)
        reason = blocking_reason(report)
    except Exception as exc:  # any crash becomes a stored, readable failure
        if not isinstance(exc, FileNotFoundError | QualityReportError | ValueError):
            logger.exception("Quality report crashed for dataset %s", dataset_id)
        reason = _failure_reason(exc)

    with transaction.atomic():
        dataset = (
            Dataset.objects.select_for_update()
            .filter(pk=dataset_id, status=DatasetStatus.VALIDATING, validation_run=run_id)
            .first()
        )
        if dataset is None:  # the mapping changed or a newer run started meanwhile
            return "skipped"
        dataset.status = DatasetStatus.FAILED if reason else DatasetStatus.VALIDATED
        dataset.quality_report = report
        dataset.validated_at = timezone.now()
        dataset.validation_error = reason
        dataset.validation_run = None
        dataset.save(update_fields=_VALIDATION_FIELDS)
        record(
            AuditAction.DATASET_VALIDATE,
            workspace=dataset.workspace,
            target_type="dataset",
            target_id=dataset.pk,
            dataset_name=dataset.name,
            phase="failed" if reason else "completed",
            status=dataset.status,
            severity=report["severity"] if report else None,
            reason=reason,
        )
    return dataset.status
