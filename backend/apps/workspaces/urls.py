from rest_framework.routers import SimpleRouter

from .member_views import router as member_router
from .views import WorkspaceViewSet

router = SimpleRouter()
router.register("workspaces", WorkspaceViewSet, basename="workspace")

urlpatterns = [*router.urls, *member_router.urls]
