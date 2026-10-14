"""Test settings: SQLite unless POSTGRES_HOST is provided (CI), eager Celery."""

import os

from .dev import *  # noqa: F403

MEDIA_ROOT = str(BASE_DIR / ".pytest_tmp" / "media")  # noqa: F405
CELERY_TASK_ALWAYS_EAGER = True
CELERY_RESULT_BACKEND = "cache+memory://"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {"login": "5/min", "register": "3/min"},
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

if not os.environ.get("POSTGRES_HOST"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# Test-only app and routes used to prove workspace scoping; absent from dev/prod settings.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.probe_app"]  # noqa: F405
ROOT_URLCONF = "tests.urls"
