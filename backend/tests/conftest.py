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


@pytest.fixture
def two_workspaces(make_user):
    """Two workspaces; in each, one user per role (plus an outsider with no membership).

    Returns a dict ``{"a": {...}, "b": {...}, "outsider": user}`` where each workspace
    entry holds ``workspace`` and the users keyed ``owner``, ``analyst``, ``viewer``.
    """
    from apps.workspaces.models import Membership
    from apps.workspaces.services import create_workspace

    result = {}
    for key in ("a", "b"):
        owner = make_user(f"{key}-owner")
        workspace = create_workspace(user=owner, name=f"Workspace {key.upper()}")
        entry = {"workspace": workspace, "owner": owner}
        for role in ("analyst", "viewer"):
            user = make_user(f"{key}-{role}")
            Membership.objects.create(user=user, workspace=workspace, role=role)
            entry[role] = user
        result[key] = entry
    result["outsider"] = make_user("outsider")
    return result
