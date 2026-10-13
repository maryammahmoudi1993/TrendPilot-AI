"""Building blocks every workspace-scoped app reuses.

* ``WorkspaceScopedModel``   abstract base: a ``workspace`` FK plus a scoped manager.
* ``WorkspaceScopedQuerySet`` ``for_user`` / ``for_workspace`` filters.
* ``WorkspaceScopedViewSetMixin`` DRF mixin for routes under
  ``/api/workspaces/{workspace_id}/...``: resolves the caller's membership (404 for
  non-members), scopes the queryset, stamps ``workspace`` on create and enforces roles.
* ``workspace_prefix(name)``  the router prefix for such nested routes.
"""

import uuid

from django.db import models
from django.http import Http404
from rest_framework.permissions import IsAuthenticated

from .models import Membership, Workspace
from .permissions import WorkspaceRolePermission
from .querysets import WorkspaceScopedManager, WorkspaceScopedQuerySet

__all__ = [
    "WORKSPACE_ID_PATTERN",
    "WorkspaceScopedManager",
    "WorkspaceScopedModel",
    "WorkspaceScopedQuerySet",
    "WorkspaceScopedViewSetMixin",
    "workspace_prefix",
]

WORKSPACE_ID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def workspace_prefix(name: str) -> str:
    """Router prefix: ``workspaces/{workspace_id}/<name>``."""
    return rf"workspaces/(?P<workspace_id>{WORKSPACE_ID_PATTERN})/{name}"


class WorkspaceScopedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="%(app_label)s_%(class)s_set"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        abstract = True
        ordering = ["created_at", "id"]


class WorkspaceScopedViewSetMixin:
    """Put this first in the bases: ``class X(WorkspaceScopedViewSetMixin, ModelViewSet)``."""

    permission_classes = [IsAuthenticated, WorkspaceRolePermission]
    workspace_url_kwarg = "workspace_id"
    required_actions: dict = {}

    def get_membership(self) -> Membership:
        if not hasattr(self, "_membership"):
            membership = (
                Membership.objects.select_related("workspace")
                .filter(workspace_id=self.kwargs[self.workspace_url_kwarg], user=self.request.user)
                .first()
            )
            if membership is None:
                raise Http404("Not found.")
            self._membership = membership
        return self._membership

    @property
    def workspace(self) -> Workspace:
        return self.get_membership().workspace

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):  # schema generation has no request user
            return queryset.none()
        return queryset.for_user(self.request.user).for_workspace(self.workspace)

    def perform_create(self, serializer):
        serializer.save(workspace=self.workspace)
