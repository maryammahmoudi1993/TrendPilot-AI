import hashlib

from django.conf import settings
from rest_framework import serializers

from .dates import DATE_ORDERS, validate_timezone
from .models import Dataset
from .services import upload_dataset
from .validation import CsvSniffError, sniff_csv


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dataset
        fields = [
            "id",
            "name",
            "original_filename",
            "size",
            "sha256",
            "status",
            "row_count",
            "upload_report",
            "column_mapping",
            "detected_frequency",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DatasetUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)

    class Meta:
        model = Dataset
        fields = ["name", "file"]

    def validate_file(self, value):
        if not value.name.lower().endswith(".csv"):
            raise serializers.ValidationError("Only .csv files are accepted.")

        raw = value.read()  # DRF's FileField already rejects an empty upload before this runs
        if len(raw) > settings.DATASET_MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                f"The file exceeds the {settings.DATASET_MAX_UPLOAD_BYTES} byte limit."
            )

        try:
            info = sniff_csv(raw)
        except CsvSniffError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if info["row_count"] > settings.DATASET_MAX_ROWS:
            raise serializers.ValidationError(
                f"The file has more than {settings.DATASET_MAX_ROWS} rows."
            )

        workspace = self.context["view"].workspace
        sha256 = hashlib.sha256(raw).hexdigest()
        if Dataset.objects.filter(workspace=workspace, sha256=sha256).exists():
            raise serializers.ValidationError(
                "This file has already been uploaded to this workspace."
            )

        self._raw = raw
        self._sha256 = sha256
        self._row_count = info["row_count"]
        self._upload_report = {
            "delimiter": info["delimiter"],
            "blank_lines": info["blank_lines"],
            "ragged": info["ragged"],
        }
        return value

    def create(self, validated_data):
        workspace = validated_data["workspace"]
        file = validated_data["file"]
        name = validated_data.get("name") or file.name
        return upload_dataset(
            workspace=workspace,
            actor=self.context["request"].user,
            original_filename=file.name,
            raw=self._raw,
            sha256=self._sha256,
            row_count=self._row_count,
            upload_report=self._upload_report,
            name=name,
        )


class MappingSerializer(serializers.Serializer):
    """Roles for the dataset's columns plus optional parsing hints."""

    date = serializers.CharField(help_text="Column holding the timestamp.")
    target = serializers.CharField(help_text="Numeric column to forecast.")
    series_id = serializers.CharField(
        required=False, allow_null=True, help_text="Optional column identifying each series."
    )
    regressors = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Optional numeric columns."
    )
    date_order = serializers.ChoiceField(
        choices=DATE_ORDERS,
        required=False,
        allow_null=True,
        help_text="Resolve day-first ('dmy') vs month-first ('mdy') dates.",
    )
    timezone = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="IANA timezone for dates without a UTC offset, e.g. Europe/Berlin.",
    )
    decimal_separator = serializers.ChoiceField(
        choices=[".", ","],
        required=False,
        allow_null=True,
        help_text="Force the decimal mark when a number column is ambiguous.",
    )

    def validate_timezone(self, value):
        if value is None:
            return value
        try:
            return validate_timezone(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
