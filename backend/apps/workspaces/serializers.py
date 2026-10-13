from rest_framework import serializers

from .models import Workspace
from .services import create_workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    role = serializers.CharField(read_only=True, help_text="The caller's role in this workspace.")

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "role", "created_at", "updated_at"]
        read_only_fields = ["id", "slug", "role", "created_at", "updated_at"]

    def create(self, validated_data):
        user = self.context["request"].user
        workspace = create_workspace(user=user, name=validated_data["name"])
        workspace.role = "owner"
        return workspace
