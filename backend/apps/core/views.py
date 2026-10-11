import logging

import redis
from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return "ok"
    except Exception:
        logger.exception("health: database check failed")
        return "error"


def check_redis() -> str:
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        return "ok"
    except Exception:
        logger.warning("health: redis check failed")
        return "error"


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def health(request: Request) -> Response:
    return Response(
        {
            "status": "ok",
            "service": "trendpilot-api",
            "version": settings.APP_VERSION,
            "database": check_database(),
            "redis": check_redis(),
        }
    )
