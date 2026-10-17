"""Base settings shared by every environment. All values come from env vars."""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "apps.accounts",
    "apps.workspaces",
    "apps.audit",
    "apps.datasets",
    "apps.core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "trendpilot"),
        "USER": os.environ.get("POSTGRES_USER", "trendpilot"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "mahmoodi.maryam1993@gmail.com")

# Uploaded datasets live here, never under a URL Django serves directly: reading them
# back must always go through an authenticated, workspace-scoped endpoint.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media"))
MEDIA_URL = "media/"

DATASET_MAX_UPLOAD_BYTES = int(os.environ.get("DATASET_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
DATASET_MAX_ROWS = int(os.environ.get("DATASET_MAX_ROWS", "500000"))
# Share of rows allowed to have a different field count than the header (padded or
# truncated on read). Above it the upload is rejected; at least one row is always allowed.
# Rows per chunk when a stored CSV is read for parsing or the quality report.
DATASET_READ_CHUNK_ROWS = int(os.environ.get("DATASET_READ_CHUNK_ROWS", "50000"))
DATASET_MAX_RAGGED_SHARE = float(os.environ.get("DATASET_MAX_RAGGED_SHARE", "0.01"))
# Share of non-empty cells in a target/regressor column that must convert to numbers.
DATASET_MIN_NUMERIC_SHARE = float(os.environ.get("DATASET_MIN_NUMERIC_SHARE", "0.95"))
# Stricter bar for the target: silently losing the values we forecast is worse than for a
# regressor. Cells that fail conversion are kept as missing, never dropped.
DATASET_MIN_TARGET_NUMERIC_SHARE = float(os.environ.get("DATASET_MIN_TARGET_NUMERIC_SHARE", "0.99"))

# Quality report: series with fewer usable target values than this are an error (and block
# modelling when every series is that short) or a warning respectively.
DATASET_MIN_OBSERVATIONS_ERROR = int(os.environ.get("DATASET_MIN_OBSERVATIONS_ERROR", "10"))
DATASET_MIN_OBSERVATIONS_WARN = int(os.environ.get("DATASET_MIN_OBSERVATIONS_WARN", "50"))

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Throttle counters live in the cache so they are shared between worker processes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "login": os.environ.get("THROTTLE_LOGIN_RATE", "10/min"),
        "register": os.environ.get("THROTTLE_REGISTER_RATE", "5/hour"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TrendPilot AI API",
    "DESCRIPTION": (
        "Forecasting and anomaly detection for small businesses. Authenticate with "
        "`POST /api/auth/login/` and send `Authorization: Bearer <access>`. Errors share the "
        'shape `{"error": {"code", "message", "details?"}}`.'
    ),
    "VERSION": APP_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "COMPONENT_SPLIT_REQUEST": True,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "10"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
