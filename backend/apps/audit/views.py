from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets

from apps.core.schema import errors
from apps.workspaces.matrix import Action
from apps.workspaces.scoping import WorkspaceScopedViewSetMixin

from .models import AuditAction, AuditEvent
from .serializers import AuditEventSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List audit events of a workspace (Owners only)",
        responses={200: AuditEventSerializer, **errors(403, 404)},
        parameters=[OpenApiParameter("action", enum=AuditAction.values, required=False)],
    ),
    retrieve=extend_schema(
        summary="Get one audit event (Owners only)",
        responses={200: AuditEventSerializer, **errors(403, 404)},
    ),
)
class AuditEventViewSet(WorkspaceScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.select_related("actor")
    serializer_class = AuditEventSerializer
    required_actions = {"list": Action.VIEW_AUDIT, "retrieve": Action.VIEW_AUDIT}

    def get_queryset(self):
        queryset = super().get_queryset()
        action = self.request.query_params.get("action") if self.request else None
        if action:
            queryset = queryset.filter(action=action)
        return queryset
