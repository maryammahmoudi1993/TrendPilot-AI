"""Test settings: SQLite unless POSTGRES_HOST is provided (CI), eager Celery."""

import os

from .dev import *  # noqa: F403

CELERY_TASK_ALWAYS_EAGER = True
CELERY_RESULT_BACKEND = "cache+memory://"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

if not os.environ.get("POSTGRES_HOST"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
