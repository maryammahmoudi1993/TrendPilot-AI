import pytest

from apps.workspaces.models import Membership, Role

pytestmark = pytest.mark.django_db


def members_url(ws):
    return f"/api/workspaces/{ws.pk}/members/"


def member_url(ws, membership):
    return f"/api/workspaces/{ws.pk}/members/{membership.pk}/"


def membership_of(user, ws):
    return Membership.objects.get(user=user, workspace=ws)


def promote(user, ws):
    Membership.objects.filter(user=user, workspace=ws).update(role=Role.OWNER)


@pytest.fixture
def ws_a(two_workspaces):
    return two_workspaces["a"]


# --- list -------------------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "analyst", "viewer"])
def test_every_member_can_list_members(ws_a, client_for, role):
    response = client_for(ws_a[role]).get(members_url(ws_a["workspace"]))
    assert response.status_code == 200
    rows = response.json()["results"]
    assert {r["role"] for r in rows} == {"owner", "analyst", "viewer"}
    assert {"id", "user_id", "email", "full_name", "role", "created_at"} == set(rows[0])


def test_list_never_includes_other_workspaces_members(two_workspaces, client_for):
    response = client_for(two_workspaces["a"]["owner"]).get(
        members_url(two_workspaces["a"]["workspace"])
    )
    emails = {r["email"] for r in response.json()["results"]}
    assert len(emails) == 3
    assert not any(e.startswith("b-") for e in emails)


def test_non_member_gets_404_on_members_endpoints(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    target = membership_of(two_workspaces["a"]["viewer"], ws)
    outsider = client_for(two_workspaces["b"]["owner"])
    assert outsider.get(members_url(ws)).status_code == 404
    body = {"email": two_workspaces["outsider"].email, "role": "viewer"}
    assert outsider.post(members_url(ws), body, format="json").status_code == 404
    patch = outsider.patch(member_url(ws, target), {"role": "owner"}, format="json")
    assert patch.status_code == 404
    assert outsider.delete(member_url(ws, target)).status_code == 404
    assert outsider.post(members_url(ws) + "leave/").status_code == 404
    target.refresh_from_db()
    assert target.role == Role.VIEWER


def test_anonymous_gets_401(ws_a, client_for):
    assert client_for().get(members_url(ws_a["workspace"])).status_code == 401


# --- add --------------------------------------------------------------------


def test_owner_adds_an_existing_user_by_email_case_insensitively(two_workspaces, ws_a, client_for):
    newcomer = two_workspaces["outsider"]
    response = client_for(ws_a["owner"]).post(
        members_url(ws_a["workspace"]),
        {"email": newcomer.email.upper(), "role": "analyst"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["email"] == newcomer.email
    assert membership_of(newcomer, ws_a["workspace"]).role == Role.ANALYST


def test_add_unknown_email_is_a_validation_error(ws_a, client_for):
    body = {"email": "ghost" + "@example.org", "role": "viewer"}
    response = client_for(ws_a["owner"]).post(members_url(ws_a["workspace"]), body, format="json")
    assert response.status_code == 400
    assert "email" in response.json()["error"]["details"]


def test_add_inactive_user_is_rejected(make_user, ws_a, client_for):
    gone = make_user("gone", is_active=False)
    response = client_for(ws_a["owner"]).post(
        members_url(ws_a["workspace"]), {"email": gone.email, "role": "viewer"}, format="json"
    )
    assert response.status_code == 400


def test_add_existing_member_is_rejected(ws_a, client_for):
    response = client_for(ws_a["owner"]).post(
        members_url(ws_a["workspace"]),
        {"email": ws_a["viewer"].email, "role": "analyst"},
        format="json",
    )
    assert response.status_code == 400
    assert membership_of(ws_a["viewer"], ws_a["workspace"]).role == Role.VIEWER


@pytest.mark.parametrize("role", ["", "admin", None])
def test_add_with_invalid_role_is_rejected(two_workspaces, ws_a, client_for, role):
    response = client_for(ws_a["owner"]).post(
        members_url(ws_a["workspace"]),
        {"email": two_workspaces["outsider"].email, "role": role},
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.json()["error"]["details"]


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_only_owner_can_add_members(two_workspaces, ws_a, client_for, role):
    response = client_for(ws_a[role]).post(
        members_url(ws_a["workspace"]),
        {"email": two_workspaces["outsider"].email, "role": "viewer"},
        format="json",
    )
    assert response.status_code == 403
    assert not Membership.objects.filter(user=two_workspaces["outsider"]).exists()


# --- change role --------------------------------------------------------------


def test_owner_changes_a_role(ws_a, client_for):
    target = membership_of(ws_a["viewer"], ws_a["workspace"])
    response = client_for(ws_a["owner"]).patch(
        member_url(ws_a["workspace"], target), {"role": "analyst"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["role"] == "analyst"
    target.refresh_from_db()
    assert target.role == Role.ANALYST


def test_change_role_validates_role(ws_a, client_for):
    target = membership_of(ws_a["viewer"], ws_a["workspace"])
    response = client_for(ws_a["owner"]).patch(
        member_url(ws_a["workspace"], target), {"role": "boss"}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_non_owners_cannot_change_roles_not_even_their_own(ws_a, client_for, role):
    own = membership_of(ws_a[role], ws_a["workspace"])
    response = client_for(ws_a[role]).patch(
        member_url(ws_a["workspace"], own), {"role": "owner"}, format="json"
    )
    assert response.status_code == 403
    own.refresh_from_db()
    assert own.role == role


def test_membership_of_another_workspace_is_404_via_my_path(two_workspaces, ws_a, client_for):
    foreign = membership_of(two_workspaces["b"]["viewer"], two_workspaces["b"]["workspace"])
    client = client_for(ws_a["owner"])
    path = member_url(ws_a["workspace"], foreign)
    assert client.patch(path, {"role": "owner"}, format="json").status_code == 404
    assert client.delete(path).status_code == 404
    foreign.refresh_from_db()
    assert foreign.role == Role.VIEWER


def test_last_owner_cannot_be_demoted(ws_a, client_for):
    own = membership_of(ws_a["owner"], ws_a["workspace"])
    response = client_for(ws_a["owner"]).patch(
        member_url(ws_a["workspace"], own), {"role": "analyst"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"
    own.refresh_from_db()
    assert own.role == Role.OWNER


def test_ownership_transfer_promote_then_demote_self(ws_a, client_for):
    ws = ws_a["workspace"]
    client = client_for(ws_a["owner"])
    heir = membership_of(ws_a["analyst"], ws)
    me = membership_of(ws_a["owner"], ws)
    assert client.patch(member_url(ws, heir), {"role": "owner"}, format="json").status_code == 200
    assert client.patch(member_url(ws, me), {"role": "analyst"}, format="json").status_code == 200
    assert membership_of(ws_a["owner"], ws).role == Role.ANALYST
    # the former owner has lost manage rights ...
    assert client.patch(member_url(ws, heir), {"role": "viewer"}, format="json").status_code == 403
    # ... and the new owner holds them
    back = client_for(ws_a["analyst"]).patch(member_url(ws, me), {"role": "owner"}, format="json")
    assert back.status_code == 200


def test_one_of_two_owners_can_be_demoted(ws_a, client_for):
    ws = ws_a["workspace"]
    promote(ws_a["analyst"], ws)
    own = membership_of(ws_a["owner"], ws)
    response = client_for(ws_a["owner"]).patch(
        member_url(ws, own), {"role": "viewer"}, format="json"
    )
    assert response.status_code == 200


# --- remove / leave --------------------------------------------------------------


def test_owner_removes_a_member(ws_a, client_for):
    target = membership_of(ws_a["analyst"], ws_a["workspace"])
    response = client_for(ws_a["owner"]).delete(member_url(ws_a["workspace"], target))
    assert response.status_code == 204
    assert not Membership.objects.filter(pk=target.pk).exists()
    # the removed user now gets 404 on the workspace
    assert client_for(ws_a["analyst"]).get(members_url(ws_a["workspace"])).status_code == 404


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_non_owners_cannot_remove_anyone(ws_a, client_for, role):
    target = membership_of(ws_a["viewer"], ws_a["workspace"])
    response = client_for(ws_a[role]).delete(member_url(ws_a["workspace"], target))
    assert response.status_code == 403
    assert Membership.objects.filter(pk=target.pk).exists()


def test_last_owner_cannot_be_removed(ws_a, client_for):
    own = membership_of(ws_a["owner"], ws_a["workspace"])
    response = client_for(ws_a["owner"]).delete(member_url(ws_a["workspace"], own))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"
    assert Membership.objects.filter(pk=own.pk).exists()


def test_an_owner_can_remove_another_owner(ws_a, client_for):
    ws = ws_a["workspace"]
    promote(ws_a["analyst"], ws)
    second = membership_of(ws_a["analyst"], ws)
    assert client_for(ws_a["owner"]).delete(member_url(ws, second)).status_code == 204


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_non_owner_members_can_leave(ws_a, client_for, role):
    response = client_for(ws_a[role]).post(members_url(ws_a["workspace"]) + "leave/")
    assert response.status_code == 204
    assert not Membership.objects.filter(user=ws_a[role], workspace=ws_a["workspace"]).exists()
    assert client_for(ws_a[role]).get(members_url(ws_a["workspace"])).status_code == 404


def test_last_owner_cannot_leave(ws_a, client_for):
    response = client_for(ws_a["owner"]).post(members_url(ws_a["workspace"]) + "leave/")
    assert response.status_code == 409
    assert Membership.objects.filter(user=ws_a["owner"], workspace=ws_a["workspace"]).exists()


def test_an_owner_can_leave_when_another_owner_exists(ws_a, client_for):
    ws = ws_a["workspace"]
    promote(ws_a["analyst"], ws)
    assert client_for(ws_a["owner"]).post(members_url(ws) + "leave/").status_code == 204


def test_leaving_does_not_touch_other_workspaces(two_workspaces, client_for):
    both = two_workspaces["outsider"]
    for key in ("a", "b"):
        Membership.objects.create(
            user=both, workspace=two_workspaces[key]["workspace"], role="viewer"
        )
    client_for(both).post(members_url(two_workspaces["a"]["workspace"]) + "leave/")
    assert Membership.objects.filter(user=both).count() == 1
    assert Membership.objects.get(user=both).workspace == two_workspaces["b"]["workspace"]
