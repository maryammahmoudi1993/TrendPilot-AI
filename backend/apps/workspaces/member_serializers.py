from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Membership, Role

User = get_user_model()


class MemberSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "email", "full_name", "role", "created_at"]
        read_only_fields = fields


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices)

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value.strip(), is_active=True).first()
        if user is None:
            raise serializers.ValidationError("No user with this email address.")
        if Membership.objects.filter(workspace=self.context["workspace"], user=user).exists():
            raise serializers.ValidationError("This user is already a member.")
        return user


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)
