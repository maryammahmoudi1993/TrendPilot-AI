from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.workspaces.matrix import Action
from apps.workspaces.scoping import WorkspaceScopedViewSetMixin, workspace_prefix

from .models import Probe


class ProbeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Probe
        fields = ["id", "name", "workspace"]
        read_only_fields = ["id", "workspace"]


class ProbeViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Probe.objects.all()
    serializer_class = ProbeSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    required_actions = {"touch": Action.EDIT}

    @action(detail=False, methods=["post"])
    def touch(self, request, workspace_id=None):
        """Custom action mapped to EDIT through ``required_actions``."""
        return Response({"touched": self.get_queryset().count()})

    @action(detail=False, methods=["post"])
    def unmapped(self, request, workspace_id=None):
        """Custom action with no mapping: must be denied for everyone."""
        return Response({"reached": True})


router = SimpleRouter()
router.register(workspace_prefix("probes"), ProbeViewSet, basename="probe")
urlpatterns = router.urls
