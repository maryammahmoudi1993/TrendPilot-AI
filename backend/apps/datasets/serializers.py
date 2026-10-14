import hashlib

from django.conf import settings
from rest_framework import serializers

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
            name=name,
        )
