import secrets

from django.conf import settings
from django.db import models

from apps.workspaces.scoping import WorkspaceScopedModel


class DatasetStatus(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    VALIDATING = "validating", "Validating"
    VALIDATED = "validated", "Validated"
    FAILED = "failed", "Failed"


def dataset_upload_path(instance, filename):
    """Storage path for an uploaded dataset.

    The client's filename is never used for the path (it's kept separately in
    ``original_filename``); a random name avoids path traversal and collisions.
    """
    return f"datasets/{instance.workspace_id}/{secrets.token_hex(16)}.csv"


class Dataset(WorkspaceScopedModel):
    """A workspace's uploaded CSV, its storage location, and its validation state."""

    name = models.CharField(max_length=200)
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=dataset_upload_path)
    size = models.PositiveBigIntegerField(help_text="File size in bytes.")
    sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=10, choices=DatasetStatus.choices, default=DatasetStatus.UPLOADED
    )
    row_count = models.PositiveIntegerField(null=True, blank=True)
    upload_report = models.JSONField(
        default=dict,
        blank=True,
        help_text="Facts found at upload: delimiter and ragged rows (count and first lines).",
    )
    column_mapping = models.JSONField(default=dict, blank=True)
    quality_report = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Versioned data-quality report (see docs/datasets.md); null until validated.",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validation_error = models.TextField(
        blank=True, default="", help_text="Readable reason when validation failed."
    )
    validation_run = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        help_text="Token of the validation run in progress; a stale run's result is discarded.",
    )
    detected_frequency = models.CharField(max_length=20, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_datasets",
    )

    class Meta(WorkspaceScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "sha256"], name="datasets_dataset_workspace_sha256_unique"
            )
        ]

    def __str__(self):
        return self.name
