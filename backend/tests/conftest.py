import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; isolate every test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    """Create a user with a unique fake address."""
    from django.contrib.auth import get_user_model

    from tests.helpers import STRONG_PASSWORD, addr

    def factory(local: str, **extra):
        return get_user_model().objects.create_user(addr(local), STRONG_PASSWORD, **extra)

    return factory


@pytest.fixture
def client_for():
    """Return an API client authenticated as the given user (None -> anonymous)."""

    def factory(user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    return factory
