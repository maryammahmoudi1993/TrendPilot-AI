import io

import pytest
import yaml
from django.core.management import call_command

SCHEMA_URL = "/api/schema/"

PHASE_1_PATHS = {
    "/api/auth/register/": {"post"},
    "/api/auth/login/": {"post"},
    "/api/auth/refresh/": {"post"},
    "/api/auth/logout/": {"post"},
    "/api/auth/me/": {"get", "patch"},
    "/api/auth/change-password/": {"post"},
    "/api/workspaces/": {"get", "post"},
    "/api/workspaces/{id}/": {"get", "patch", "delete"},
    "/api/workspaces/{workspace_id}/members/": {"get", "post"},
    "/api/workspaces/{workspace_id}/members/{id}/": {"patch", "delete"},
    "/api/workspaces/{workspace_id}/members/leave/": {"post"},
    "/api/workspaces/{workspace_id}/audit/": {"get"},
    "/api/workspaces/{workspace_id}/audit/{id}/": {"get"},
}


@pytest.fixture
def schema(client_for):
    response = client_for().get(SCHEMA_URL, {"format": "json"})
    assert response.status_code == 200
    return response.json()


def test_schema_endpoint_is_public_and_returns_openapi3(client_for):
    response = client_for().get(SCHEMA_URL)
    assert response.status_code == 200
    document = yaml.safe_load(response.content)
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "TrendPilot AI API"


def test_schema_contains_every_phase_1_path_and_method(schema):
    for path, methods in PHASE_1_PATHS.items():
        assert path in schema["paths"], path
        assert methods <= set(schema["paths"][path]), path


def test_schema_documents_security_and_error_bodies(schema):
    assert "jwtAuth" in schema["components"]["securitySchemes"]
    assert "ErrorResponse" in schema["components"]["schemas"]
    member_patch = schema["paths"]["/api/workspaces/{workspace_id}/members/{id}/"]["patch"]
    assert {"200", "400", "403", "404", "409"} <= set(member_patch["responses"])


def test_schema_generates_without_warnings():
    out = io.StringIO()
    call_command("spectacular", "--validate", "--fail-on-warn", stdout=out, stderr=io.StringIO())
    assert "openapi" in out.getvalue()


def test_docs_page_is_served(client_for):
    response = client_for().get("/api/docs/")
    assert response.status_code == 200
    assert b"swagger" in response.content.lower()
