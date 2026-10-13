from rest_framework.routers import SimpleRouter

from .views import WorkspaceViewSet

router = SimpleRouter()
router.register("workspaces", WorkspaceViewSet, basename="workspace")

urlpatterns = router.urls
