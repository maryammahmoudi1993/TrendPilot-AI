from django.http import Http404
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import api_exception_handler


def handle(exc):
    context = {"view": None, "request": APIRequestFactory().get("/")}
    return api_exception_handler(exc, context)


def test_validation_error_has_details():
    response = handle(exceptions.ValidationError({"email": ["bad"]}))
    assert response.status_code == 400
    assert response.data == {
        "error": {
            "code": "validation_error",
            "message": "Invalid input.",
            "details": {"email": ["bad"]},
        }
    }


def test_not_authenticated():
    response = handle(exceptions.NotAuthenticated())
    assert response.status_code == 401
    assert response.data["error"]["code"] == "not_authenticated"


def test_http404_is_converted():
    response = handle(Http404())
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


def test_permission_denied_is_converted():
    response = handle(exceptions.PermissionDenied("nope"))
    assert response.status_code == 403
    assert response.data["error"] == {"code": "permission_denied", "message": "nope"}


def test_throttled_reports_retry_after():
    response = handle(exceptions.Throttled(wait=12.4))
    assert response.status_code == 429
    assert response.data["error"]["details"] == {"retry_after": 13}  # DRF rounds the wait up


def test_unhandled_exceptions_are_left_to_django():
    assert handle(RuntimeError("boom")) is None
