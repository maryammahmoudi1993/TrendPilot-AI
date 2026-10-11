import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured


def _load(module: str, monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(importlib.import_module("config.settings.base"))
    return importlib.reload(importlib.import_module(module))


def test_dev_settings_load(monkeypatch):
    mod = _load("config.settings.dev", monkeypatch, DJANGO_SECRET_KEY="dev-key")
    assert mod.DEBUG is True
    assert mod.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert "rest_framework" in mod.INSTALLED_APPS


def test_prod_settings_load(monkeypatch):
    mod = _load(
        "config.settings.prod",
        monkeypatch,
        DJANGO_SECRET_KEY="prod-key",
        DJANGO_ALLOWED_HOSTS="api.example.com",
    )
    assert mod.DEBUG is False
    assert mod.ALLOWED_HOSTS == ["api.example.com"]
    assert mod.SECURE_CONTENT_TYPE_NOSNIFF is True


def test_prod_requires_secret_key(monkeypatch):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    importlib.reload(importlib.import_module("config.settings.base"))
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        importlib.reload(importlib.import_module("config.settings.prod"))


def test_celery_broker_comes_from_env(monkeypatch):
    mod = _load("config.settings.dev", monkeypatch, REDIS_URL="redis://cache:6379/1")
    assert mod.CELERY_BROKER_URL == "redis://cache:6379/1"


def test_logging_uses_json_formatter():
    from django.conf import settings

    formatter = settings.LOGGING["formatters"]["json"]
    assert "JsonFormatter" in formatter["()"]
