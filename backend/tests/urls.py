"""Root URLconf for the test settings: the real routes plus the probe endpoints."""

from django.urls import include, path

from config.urls import urlpatterns as project_urlpatterns

urlpatterns = [*project_urlpatterns, path("api/", include("tests.probe_app.api"))]
