import uuid

import pytest

from apps.workspaces.models import Membership, Role, Workspace
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db

LIST = "/api/workspaces/"


def detail(workspace_id):
    return f"/api/workspaces/{workspace_id}/"


def test_requires_authentication(client_for):
    assert client_for().get(LIST).status_code == 401
    assert client_for().post(LIST, {"name": "x"}, format="json").status_code == 401


def test_create_makes_caller_the_owner(make_user, client_for):
    user = make_user("ada")
    response = client_for(user).post(LIST, {"name": "  Acme Sales "}, format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Sales"
    assert body["slug"] == "acme-sales"
    assert body["role"] == "owner"
    membership = Membership.objects.get(workspace_id=body["id"])
    assert (membership.user, membership.role) == (user, Role.OWNER)


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 121}])
def test_create_validates_name(make_user, client_for, payload):
    response = client_for(make_user("ada")).post(LIST, payload, format="json")
    assert response.status_code == 400
    assert "name" in response.json()["error"]["details"]
    assert not Workspace.objects.exists()


def test_client_cannot_set_slug_or_role(make_user, client_for):
    response = client_for(make_user("ada")).post(
        LIST, {"name": "Acme", "slug": "hacked", "role": "viewer"}, format="json"
    )
    assert response.json()["slug"] == "acme"
    assert response.json()["role"] == "owner"


def test_list_shows_only_own_workspaces_with_role(make_user, client_for):
    ada, grace = make_user("ada"), make_user("grace")
    mine = create_workspace(user=ada, name="Mine")
    shared = create_workspace(user=grace, name="Shared")
    Membership.objects.create(user=ada, workspace=shared, role=Role.VIEWER)
    create_workspace(user=grace, name="Secret")

    body = client_for(ada).get(LIST).json()
    assert body["count"] == 2
    roles = {item["id"]: item["role"] for item in body["results"]}
    assert roles == {str(mine.pk): "owner", str(shared.pk): "viewer"}


def test_list_is_empty_for_a_user_without_workspaces(make_user, client_for):
    assert client_for(make_user("ada")).get(LIST).json()["results"] == []


def test_retrieve_as_member(make_user, client_for):
    ada = make_user("ada")
    workspace = create_workspace(user=ada, name="Acme")
    response = client_for(ada).get(detail(workspace.pk))
    assert response.status_code == 200
    assert response.json()["id"] == str(workspace.pk)


def test_non_member_gets_404_not_403(make_user, client_for):
    workspace = create_workspace(user=make_user("ada"), name="Acme")
    outsider = client_for(make_user("mallory"))
    assert outsider.get(detail(workspace.pk)).status_code == 404
    assert outsider.patch(detail(workspace.pk), {"name": "x"}, format="json").status_code == 404
    assert outsider.delete(detail(workspace.pk)).status_code == 404
    assert Workspace.objects.get(pk=workspace.pk).name == "Acme"


def test_unknown_workspace_gives_the_same_404(make_user, client_for):
    user = make_user("ada")
    existing = create_workspace(user=make_user("grace"), name="Acme")
    client = client_for(user)
    unknown = client.get(detail(uuid.uuid4()))
    hidden = client.get(detail(existing.pk))
    assert unknown.status_code == hidden.status_code == 404
    assert unknown.json() == hidden.json()


def test_owner_can_rename(make_user, client_for):
    ada = make_user("ada")
    workspace = create_workspace(user=ada, name="Acme")
    response = client_for(ada).patch(detail(workspace.pk), {"name": "Acme Co"}, format="json")
    assert response.status_code == 200
    assert response.json()["name"] == "Acme Co"
    assert response.json()["slug"] == "acme"


@pytest.mark.parametrize("role", [Role.ANALYST, Role.VIEWER])
def test_non_owner_members_cannot_rename_or_delete(make_user, client_for, role):
    workspace = create_workspace(user=make_user("ada"), name="Acme")
    member = make_user("grace")
    Membership.objects.create(user=member, workspace=workspace, role=role)
    client = client_for(member)
    assert client.patch(detail(workspace.pk), {"name": "x"}, format="json").status_code == 403
    assert client.delete(detail(workspace.pk)).status_code == 403
    assert Workspace.objects.filter(pk=workspace.pk, name="Acme").exists()


def test_put_is_not_allowed(make_user, client_for):
    ada = make_user("ada")
    workspace = create_workspace(user=ada, name="Acme")
    assert (
        client_for(ada).put(detail(workspace.pk), {"name": "x"}, format="json").status_code == 405
    )


def test_owner_can_delete_and_memberships_cascade(make_user, client_for):
    ada, grace = make_user("ada"), make_user("grace")
    workspace = create_workspace(user=ada, name="Acme")
    Membership.objects.create(user=grace, workspace=workspace, role=Role.ANALYST)
    assert client_for(ada).delete(detail(workspace.pk)).status_code == 204
    assert not Workspace.objects.exists()
    assert not Membership.objects.exists()
    assert client_for(grace).get(detail(workspace.pk)).status_code == 404
