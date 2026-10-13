"""Uniform API error format.

Every error response has the shape::

    {"error": {"code": "<machine_code>", "message": "<text>", "details": {...}}}

``details`` is present for validation errors (field -> messages) and throttling.
"""

from rest_framework import exceptions
from rest_framework.views import exception_handler


def _message_and_code(exc):
    detail = exc.detail
    if isinstance(detail, dict) and "detail" in detail:  # e.g. simplejwt token errors
        code = detail.get("code") or exc.default_code
        return str(detail["detail"]), str(code)
    if isinstance(detail, list | dict):
        return str(exc.default_detail), str(exc.default_code)
    return str(detail), str(exc.get_codes())


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        error = {
            "code": "validation_error",
            "message": "Invalid input.",
            "details": response.data,
        }
    elif isinstance(exc, exceptions.APIException):
        message, code = _message_and_code(exc)
        error = {"code": code, "message": message}
        if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
            error["details"] = {"retry_after": int(exc.wait)}
    else:  # Http404 / PermissionDenied converted by DRF
        error = {
            "code": "not_found" if response.status_code == 404 else "permission_denied",
            "message": str(response.data.get("detail", "")),
        }
    response.data = {"error": error}
    return response
