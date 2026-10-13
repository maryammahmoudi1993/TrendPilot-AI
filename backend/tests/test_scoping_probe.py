"""Proves the role matrix and workspace isolation on the test-only Probe endpoint."""

import uuid

import pytest

from tests.probe_app.models import Probe

pytestmark = pytest.mark.django_db

EXPECTED = {  # (role, action) -> status; "-" means the action never happens for that role
    ("owner", "list"): 200,
    ("owner", "retrieve"): 200,
    ("owner", "create"): 201,
    ("owner", "update"): 200,
    ("owner", "delete"): 204,
    ("analyst", "list"): 200,
    ("analyst", "retrieve"): 200,
    ("analyst", "create"): 201,
    ("analyst", "update"): 200,
    ("analyst", "delete"): 204,
    ("viewer", "list"): 200,
    ("viewer", "retrieve"): 200,
    ("viewer", "create"): 403,
    ("viewer", "update"): 403,
    ("viewer", "delete"): 403,
}


def collection(ws):
    return f"/api/workspaces/{ws.pk}/probes/"


def item(ws, probe):
    return f"/api/workspaces/{ws.pk}/probes/{probe.pk}/"


def call(client, action, ws, probe):
    if action == "list":
        return client.get(collection(ws))
    if action == "create":
        return client.post(collection(ws), {"name": "new"}, format="json")
    if action == "retrieve":
        return client.get(item(ws, probe))
    if action == "update":
        return client.patch(item(ws, probe), {"name": "changed"}, format="json")
    return client.delete(item(ws, probe))


@pytest.mark.parametrize(("role", "action"), list(EXPECTED))
def test_role_action_matrix(two_workspaces, client_for, role, action):
    ws = two_workspaces["a"]["workspace"]
    probe = Probe.objects.create(workspace=ws, name="seed")
    response = call(client_for(two_workspaces["a"][role]), action, ws, probe)
    assert response.status_code == EXPECTED[(role, action)], response.content

    changed = Probe.objects.filter(pk=probe.pk).first()
    if EXPECTED[(role, action)] < 300:
        if action == "update":
            assert changed.name == "changed"
        if action == "delete":
            assert changed is None
    else:  # forbidden actions must not have touched the data
        assert changed is not None and changed.name == "seed"
        assert Probe.objects.count() == 1


@pytest.mark.parametrize("action", ["list", "create", "retrieve", "update", "delete"])
def test_unauthenticated_gets_401(two_workspaces, client_for, action):
    ws = two_workspaces["a"]["workspace"]
    probe = Probe.objects.create(workspace=ws, name="seed")
    assert call(client_for(), action, ws, probe).status_code == 401


@pytest.mark.parametrize("who", ["outsider", "b-owner"])
@pytest.mark.parametrize("action", ["list", "create", "retrieve", "update", "delete"])
def test_non_members_get_404_on_every_action(two_workspaces, client_for, who, action):
    ws = two_workspaces["a"]["workspace"]
    probe = Probe.objects.create(workspace=ws, name="seed")
    user = two_workspaces["outsider"] if who == "outsider" else two_workspaces["b"]["owner"]
    assert call(client_for(user), action, ws, probe).status_code == 404
    assert Probe.objects.get(pk=probe.pk).name == "seed"


@pytest.mark.parametrize("action", ["retrieve", "update", "delete"])
def test_other_workspaces_object_id_via_own_workspace_is_404(two_workspaces, client_for, action):
    """A member of A addressing B's object id under A's path must not reach it."""
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    foreign = Probe.objects.create(workspace=b, name="b-secret")
    response = call(client_for(two_workspaces["a"]["owner"]), action, a, foreign)
    assert response.status_code == 404
    assert Probe.objects.get(pk=foreign.pk).name == "b-secret"


def test_list_only_returns_the_requested_workspaces_rows(two_workspaces, client_for):
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    mine = Probe.objects.create(workspace=a, name="mine")
    Probe.objects.create(workspace=b, name="theirs")
    body = client_for(two_workspaces["a"]["viewer"]).get(collection(a)).json()
    assert [row["id"] for row in body["results"]] == [str(mine.pk)]


def test_user_in_both_workspaces_sees_only_the_path_workspace(
    two_workspaces, client_for, make_user
):
    from apps.workspaces.models import Membership

    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    both = make_user("both")
    Membership.objects.create(user=both, workspace=a, role="viewer")
    Membership.objects.create(user=both, workspace=b, role="analyst")
    pa = Probe.objects.create(workspace=a, name="in-a")
    pb = Probe.objects.create(workspace=b, name="in-b")
    client = client_for(both)
    assert [r["id"] for r in client.get(collection(a)).json()["results"]] == [str(pa.pk)]
    assert client.get(item(a, pb)).status_code == 404
    # roles are per workspace: viewer in A, analyst in B
    assert client.post(collection(a), {"name": "x"}, format="json").status_code == 403
    assert client.post(collection(b), {"name": "x"}, format="json").status_code == 201


def test_create_stamps_the_path_workspace_and_ignores_client_workspace(two_workspaces, client_for):
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    response = client_for(two_workspaces["a"]["analyst"]).post(
        collection(a), {"name": "x", "workspace": str(b.pk)}, format="json"
    )
    assert response.status_code == 201
    assert Probe.objects.get(pk=response.json()["id"]).workspace == a


def test_unknown_or_malformed_workspace_ids_are_404(two_workspaces, client_for):
    client = client_for(two_workspaces["a"]["owner"])
    assert client.get(f"/api/workspaces/{uuid.uuid4()}/probes/").status_code == 404
    assert client.get("/api/workspaces/not-a-uuid/probes/").status_code == 404


def test_malformed_object_id_is_404(two_workspaces, client_for):
    a = two_workspaces["a"]["workspace"]
    assert client_for(two_workspaces["a"]["owner"]).get(collection(a) + "xyz/").status_code == 404


def test_options_needs_membership_only_for_view(two_workspaces, client_for):
    a = two_workspaces["a"]["workspace"]
    assert client_for(two_workspaces["a"]["viewer"]).options(collection(a)).status_code == 200
    assert client_for(two_workspaces["outsider"]).options(collection(a)).status_code == 404


@pytest.mark.parametrize(("role", "status"), [("owner", 200), ("analyst", 200), ("viewer", 403)])
def test_custom_action_uses_required_actions_mapping(two_workspaces, client_for, role, status):
    a = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"][role]).post(collection(a) + "touch/")
    assert response.status_code == status


@pytest.mark.parametrize("role", ["owner", "analyst", "viewer"])
def test_unmapped_custom_action_is_denied_for_every_role(two_workspaces, client_for, role):
    a = two_workspaces["a"]["workspace"]
    response = client_for(two_workspaces["a"][role]).post(collection(a) + "unmapped/")
    assert response.status_code == 403


def test_queryset_helpers(two_workspaces):
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    pa = Probe.objects.create(workspace=a, name="a")
    Probe.objects.create(workspace=b, name="b")
    assert list(Probe.objects.for_user(two_workspaces["a"]["viewer"])) == [pa]
    assert list(Probe.objects.for_workspace(a)) == [pa]
    assert not Probe.objects.for_user(two_workspaces["outsider"]).exists()
    assert not Probe.objects.for_user(None).exists()
