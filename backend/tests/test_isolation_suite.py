"""Isolation regression suite: roles x actions x workspaces for every registered resource.

Phases 2-8 must register each new workspace-scoped model in ``tests/isolation.py``.
"""

import uuid

import pytest

from apps.workspaces.matrix import can
from apps.workspaces.models import Membership, Role, Workspace
from tests.isolation import (
    OPS,
    REGISTRY,
    SUCCESS_STATUS,
    registered_models,
    workspace_models_in_project,
)

pytestmark = pytest.mark.django_db

ROLES = ["owner", "analyst", "viewer"]


def cases(*, kinds=OPS):
    """(resource, op) pairs for every registered resource supporting the op."""
    return [
        pytest.param(res, op, id=f"{res.name}-{op}")
        for res in REGISTRY
        for op in kinds
        if op in res.ops
    ]


def call(client, res, op, ws, obj, ctx):
    base = res.list_url(ws)
    if op == "list":
        return client.get(base)
    if op == "create":
        fmt = "multipart" if res.extra.get("multipart") else "json"
        return client.post(base, res.create_payload(ctx), format=fmt)
    detail = f"{base}{obj.pk}/"
    if op == "retrieve":
        return client.get(detail)
    if op == "update":
        return client.patch(detail, res.update_payload(ctx), format="json")
    return client.delete(detail)


def count(res):
    return res.model.objects.count()


# --- the meta-test: nothing workspace-scoped escapes the suite ---------------------------


def test_every_workspace_scoped_model_is_registered():
    missing = {m.__name__ for m in workspace_models_in_project()} - {
        m.__name__ for m in registered_models()
    }
    assert not missing, f"Register these models in tests/isolation.py: {sorted(missing)}"


# --- generic checks, run for every registered resource ------------------------------------


@pytest.mark.parametrize(("res", "op"), cases())
def test_anonymous_gets_401(res, op, two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    obj = res.make(ws, two_workspaces)
    before = count(res)
    assert call(client_for(), res, op, ws, obj, two_workspaces).status_code == 401
    assert count(res) == before


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("res", "op"), cases())
def test_role_matrix(res, op, role, two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    obj = res.make(ws, two_workspaces)
    before = count(res)
    response = call(client_for(two_workspaces["a"][role]), res, op, ws, obj, two_workspaces)

    if can(role, res.ops[op]):
        assert response.status_code == SUCCESS_STATUS[op], response.content
        if op == "create":
            assert count(res) == before + 1
        if op == "delete":
            assert count(res) == before - 1
        if op == "update" and res.changed:
            obj.refresh_from_db()
            assert getattr(obj, res.changed[0]) == res.changed[1]
    else:
        assert response.status_code == 403, response.content
        assert count(res) == before
        obj.refresh_from_db()  # still there ...
        if res.changed:  # ... and untouched
            assert getattr(obj, res.changed[0]) != res.changed[1]


@pytest.mark.parametrize("who", ["outsider", "other-workspace-owner", "other-workspace-viewer"])
@pytest.mark.parametrize(("res", "op"), cases())
def test_non_members_get_404_not_403(res, op, who, two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    obj = res.make(ws, two_workspaces)
    user = {
        "outsider": two_workspaces["outsider"],
        "other-workspace-owner": two_workspaces["b"]["owner"],
        "other-workspace-viewer": two_workspaces["b"]["viewer"],
    }[who]
    before = count(res)
    response = call(client_for(user), res, op, ws, obj, two_workspaces)
    assert response.status_code == 404, response.content
    assert count(res) == before
    obj.refresh_from_db()
    if res.changed:
        assert getattr(obj, res.changed[0]) != res.changed[1]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("res", "op"), cases(kinds=("retrieve", "update", "delete")))
def test_other_workspaces_object_id_is_indistinguishable_from_a_random_id(
    res, op, role, two_workspaces, client_for
):
    """A member of A addressing B's object under A's URL must learn nothing.

    The response must equal the one for an id that exists nowhere, and when the caller's
    role allows the operation it must be a plain 404.
    """
    mine, theirs = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    foreign = res.make(theirs, two_workspaces)
    ghost = type("Ghost", (), {"pk": uuid.uuid4()})()
    client = client_for(two_workspaces["a"][role])
    before = count(res)

    real = call(client, res, op, mine, foreign, two_workspaces)
    fake = call(client, res, op, mine, ghost, two_workspaces)

    assert (real.status_code, real.json()) == (fake.status_code, fake.json())
    assert real.status_code == (404 if can(role, res.ops[op]) else 403)
    assert count(res) == before
    foreign.refresh_from_db()
    if res.changed:
        assert getattr(foreign, res.changed[0]) != res.changed[1]


@pytest.mark.parametrize(("res", "op"), cases(kinds=("retrieve", "update", "delete")))
def test_member_of_both_workspaces_cannot_cross_paths(res, op, two_workspaces, client_for):
    """The classic IDOR: an Owner of A *and* B addresses B's object through A's URL.

    Membership of the target workspace must not matter; only the workspace in the path
    scopes the lookup.
    """
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    user = two_workspaces["outsider"]
    Membership.objects.create(user=user, workspace=a, role=Role.OWNER)
    Membership.objects.create(user=user, workspace=b, role=Role.OWNER)
    foreign = res.make(b, two_workspaces)
    before = count(res)

    response = call(client_for(user), res, op, a, foreign, two_workspaces)

    assert response.status_code == 404, response.content
    assert count(res) == before
    foreign.refresh_from_db()
    if res.changed:
        assert getattr(foreign, res.changed[0]) != res.changed[1]


@pytest.mark.parametrize("res", [r for r in REGISTRY if "list" in r.ops], ids=str)
def test_list_never_contains_other_workspaces_rows(res, two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    mine = res.make(a["workspace"], two_workspaces)
    theirs = res.make(b["workspace"], two_workspaces)
    allowed = [role for role in ROLES if can(role, res.ops["list"])]
    for role in allowed:
        body = client_for(a[role]).get(res.list_url(a["workspace"])).json()
        ids = {row["id"] for row in body["results"]}
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids


@pytest.mark.parametrize("res", [r for r in REGISTRY if "list" in r.ops], ids=str)
def test_user_in_two_workspaces_gets_each_workspaces_own_role(res, two_workspaces, client_for):
    """Roles are per workspace: viewer in A and owner in B must not mix."""
    a, b = two_workspaces["a"]["workspace"], two_workspaces["b"]["workspace"]
    user = two_workspaces["outsider"]
    Membership.objects.create(user=user, workspace=a, role=Role.VIEWER)
    Membership.objects.create(user=user, workspace=b, role=Role.OWNER)
    client = client_for(user)
    for ws, role in ((a, "viewer"), (b, "owner")):
        status = client.get(res.list_url(ws)).status_code
        assert status == (200 if can(role, res.ops["list"]) else 403), (res.name, role)


# --- the phase's explicit acceptance tests ------------------------------------------------------


def test_user_cannot_read_other_workspace_data(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    secret = REGISTRY[0].make(b["workspace"], two_workspaces)  # a probe in workspace B
    client = client_for(a["owner"])
    assert client.get(f"/api/workspaces/{b['workspace'].pk}/").status_code == 404
    assert client.get(REGISTRY[0].list_url(b["workspace"])).status_code == 404
    assert client.get(f"{REGISTRY[0].list_url(b['workspace'])}{secret.pk}/").status_code == 404
    assert client.get(f"{REGISTRY[0].list_url(a['workspace'])}{secret.pk}/").status_code == 404
    listed = client.get("/api/workspaces/").json()["results"]
    assert [w["id"] for w in listed] == [str(a["workspace"].pk)]


def test_user_cannot_list_other_workspace_data(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    REGISTRY[0].make(b["workspace"], two_workspaces)
    body = client_for(a["owner"]).get(REGISTRY[0].list_url(a["workspace"])).json()
    assert body["results"] == []
    assert (
        client_for(a["owner"]).get(f"/api/workspaces/{b['workspace'].pk}/members/").status_code
        == 404
    )


def test_user_cannot_update_other_workspace_data(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    probe = REGISTRY[0].make(b["workspace"], two_workspaces)
    client = client_for(a["owner"])
    assert (
        client.patch(
            f"/api/workspaces/{b['workspace'].pk}/", {"name": "x"}, format="json"
        ).status_code
        == 404
    )
    url = f"{REGISTRY[0].list_url(b['workspace'])}{probe.pk}/"
    assert client.patch(url, {"name": "hacked"}, format="json").status_code == 404
    probe.refresh_from_db()
    assert probe.name == "seed"
    assert Workspace.objects.get(pk=b["workspace"].pk).name == "Workspace B"


def test_user_cannot_delete_other_workspace_data(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    probe = REGISTRY[0].make(b["workspace"], two_workspaces)
    client = client_for(a["owner"])
    assert client.delete(f"/api/workspaces/{b['workspace'].pk}/").status_code == 404
    assert client.delete(f"{REGISTRY[0].list_url(b['workspace'])}{probe.pk}/").status_code == 404
    assert Workspace.objects.filter(pk=b["workspace"].pk).exists()
    probe.refresh_from_db()


def test_viewer_cannot_upload_or_delete(two_workspaces, client_for):
    a = two_workspaces["a"]
    probe_res = REGISTRY[0]
    probe = probe_res.make(a["workspace"], two_workspaces)
    viewer = client_for(a["viewer"])
    # "upload" == create
    assert (
        viewer.post(probe_res.list_url(a["workspace"]), {"name": "x"}, format="json").status_code
        == 403
    )
    assert viewer.delete(f"{probe_res.list_url(a['workspace'])}{probe.pk}/").status_code == 403
    assert (
        viewer.patch(
            f"{probe_res.list_url(a['workspace'])}{probe.pk}/", {"name": "x"}, format="json"
        ).status_code
        == 403
    )
    probe.refresh_from_db()
    assert probe.name == "seed"
    # a viewer can still read
    assert viewer.get(probe_res.list_url(a["workspace"])).status_code == 200


def test_analyst_can_upload_and_delete_data(two_workspaces, client_for):
    a = two_workspaces["a"]
    probe_res = REGISTRY[0]
    analyst = client_for(a["analyst"])
    created = analyst.post(probe_res.list_url(a["workspace"]), {"name": "x"}, format="json")
    assert created.status_code == 201
    deleted = analyst.delete(f"{probe_res.list_url(a['workspace'])}{created.json()['id']}/")
    assert deleted.status_code == 204


def test_analyst_cannot_manage_members(two_workspaces, client_for):
    a = two_workspaces["a"]
    base = f"/api/workspaces/{a['workspace'].pk}/members/"
    viewer_membership = Membership.objects.get(user=a["viewer"], workspace=a["workspace"])
    analyst = client_for(a["analyst"])
    add = analyst.post(
        base, {"email": two_workspaces["outsider"].email, "role": "viewer"}, format="json"
    )
    assert add.status_code == 403
    assert (
        analyst.patch(
            f"{base}{viewer_membership.pk}/", {"role": "owner"}, format="json"
        ).status_code
        == 403
    )
    assert analyst.delete(f"{base}{viewer_membership.pk}/").status_code == 403
    assert Membership.objects.filter(workspace=a["workspace"]).count() == 3
    viewer_membership.refresh_from_db()
    assert viewer_membership.role == Role.VIEWER


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_only_owner_can_delete_the_workspace(role, two_workspaces, client_for):
    a = two_workspaces["a"]
    url = f"/api/workspaces/{a['workspace'].pk}/"
    assert client_for(a[role]).delete(url).status_code == 403
    assert Workspace.objects.filter(pk=a["workspace"].pk).exists()
    assert client_for(a["owner"]).delete(url).status_code == 204
    assert not Workspace.objects.filter(pk=a["workspace"].pk).exists()
    assert Workspace.objects.filter(pk=two_workspaces["b"]["workspace"].pk).exists()


def test_only_owner_can_manage_members(two_workspaces, client_for):
    a = two_workspaces["a"]
    base = f"/api/workspaces/{a['workspace'].pk}/members/"
    owner = client_for(a["owner"])
    added = owner.post(
        base, {"email": two_workspaces["outsider"].email, "role": "viewer"}, format="json"
    )
    assert added.status_code == 201
    member_url = f"{base}{added.json()['id']}/"
    assert owner.patch(member_url, {"role": "analyst"}, format="json").status_code == 200
    assert owner.delete(member_url).status_code == 204


def test_non_members_get_404_not_403_on_workspace_resources(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    outsider = client_for(two_workspaces["outsider"])
    for url in (
        f"/api/workspaces/{ws.pk}/",
        f"/api/workspaces/{ws.pk}/members/",
        f"/api/workspaces/{ws.pk}/audit/",
        f"/api/workspaces/{ws.pk}/probes/",
    ):
        assert outsider.get(url).status_code == 404, url
    unknown = client_for(two_workspaces["a"]["owner"]).get(
        "/api/workspaces/00000000-0000-0000-0000-000000000000/probes/"
    )
    # indistinguishable from a workspace that exists but is off limits
    assert unknown.json() == outsider.get(f"/api/workspaces/{ws.pk}/probes/").json()
