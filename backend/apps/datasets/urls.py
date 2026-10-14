from rest_framework.routers import SimpleRouter

from apps.workspaces.scoping import workspace_prefix

from .views import DatasetViewSet

router = SimpleRouter()
router.register(workspace_prefix("datasets"), DatasetViewSet, basename="dataset")

urlpatterns = router.urls
