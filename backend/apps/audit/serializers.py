from rest_framework import serializers

from .models import AuditEvent


class AuditActorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()


class AuditEventSerializer(serializers.ModelSerializer):
    actor = AuditActorSerializer(read_only=True, allow_null=True)

    class Meta:
        model = AuditEvent
        fields = ["id", "action", "actor", "target_type", "target_id", "metadata", "created_at"]
        read_only_fields = fields
