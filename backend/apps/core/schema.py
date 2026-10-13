"""Shared OpenAPI pieces: the uniform error body and helpers to document error codes."""

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Human-readable summary.")
    details = serializers.DictField(
        required=False, help_text="Field errors (400) or retry_after seconds (429)."
    )


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorBodySerializer()


_DESCRIPTIONS = {
    400: "Validation error.",
    401: "Missing, invalid or expired credentials.",
    403: "Authenticated, but the caller's role does not allow this action.",
    404: "Not found. Also returned for workspaces the caller is not a member of.",
    409: "Conflict, e.g. the last Owner of a workspace cannot be removed.",
    429: "Throttled; see details.retry_after.",
}


def errors(*codes: int) -> dict[int, OpenApiResponse]:
    return {
        c: OpenApiResponse(ErrorResponseSerializer, description=_DESCRIPTIONS[c]) for c in codes
    }
