from rest_framework.routers import SimpleRouter

from apps.workspaces.scoping import workspace_prefix

from .views import AuditEventViewSet

router = SimpleRouter()
router.register(workspace_prefix("audit"), AuditEventViewSet, basename="audit")

urlpatterns = router.urls
