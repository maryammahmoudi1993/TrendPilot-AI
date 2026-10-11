from unittest import mock

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_returns_200_with_expected_keys(client):
    with mock.patch("apps.core.views.check_redis", return_value="ok"):
        response = client.get("/api/health/")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "service", "version", "database", "redis"}
    assert body["status"] == "ok"
    assert body["service"] == "trendpilot-api"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["version"]


@pytest.mark.django_db
def test_health_reports_redis_error_without_failing(client):
    with mock.patch("apps.core.views.check_redis", return_value="error"):
        response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.json()["redis"] == "error"


def test_health_reports_database_error(client):
    with (
        mock.patch("apps.core.views.check_database", return_value="error"),
        mock.patch("apps.core.views.check_redis", return_value="ok"),
    ):
        response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.json()["database"] == "error"


def test_health_url_name():
    assert reverse("health") == "/api/health/"
