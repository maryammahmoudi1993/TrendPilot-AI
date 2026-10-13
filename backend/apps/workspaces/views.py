from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.schema import errors

from .models import Membership, Workspace
from .permissions import WorkspaceObjectPermission
from .serializers import WorkspaceSerializer
from .services import delete_workspace, rename_workspace


@extend_schema_view(
    list=extend_schema(summary="List the caller's workspaces", responses=WorkspaceSerializer),
    create=extend_schema(
        summary="Create a workspace; the caller becomes its Owner",
        responses={201: WorkspaceSerializer, **errors(400)},
    ),
    retrieve=extend_schema(
        summary="Get a workspace", responses={200: WorkspaceSerializer, **errors(404)}
    ),
    partial_update=extend_schema(
        summary="Rename a workspace (Owner only)",
        responses={200: WorkspaceSerializer, **errors(400, 403, 404)},
    ),
    destroy=extend_schema(
        summary="Delete a workspace and everything in it (Owner only)",
        responses={204: None, **errors(403, 404)},
    ),
)
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
        if getattr(self, "swagger_fake_view", False):
            return Workspace.objects.none()
        role = Membership.objects.filter(workspace=OuterRef("pk"), user=self.request.user).values(
            "role"
        )[:1]
        return (
            Workspace.objects.filter(memberships__user=self.request.user)
            .annotate(role=Subquery(role))
            .order_by("created_at")
        )

    def perform_update(self, serializer):
        name = serializer.validated_data.get("name", serializer.instance.name)
        rename_workspace(workspace=serializer.instance, actor=self.request.user, name=name)

    def perform_destroy(self, instance):
        delete_workspace(workspace=instance, actor=self.request.user)
