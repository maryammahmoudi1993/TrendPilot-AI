from django.db.models import OuterRef, Subquery
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Membership, Workspace
from .permissions import WorkspaceObjectPermission
from .serializers import WorkspaceSerializer


class WorkspaceViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The caller's workspaces. Workspaces the caller is not a member of are 404."""

    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated, WorkspaceObjectPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        role = Membership.objects.filter(workspace=OuterRef("pk"), user=self.request.user).values(
            "role"
        )[:1]
        return (
            Workspace.objects.filter(memberships__user=self.request.user)
            .annotate(role=Subquery(role))
            .order_by("created_at")
        )
