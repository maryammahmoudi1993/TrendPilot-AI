from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role


class WorkspaceObjectPermission(BasePermission):
    """Any member may read a workspace; only an Owner may change or delete it."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.role == Role.OWNER
