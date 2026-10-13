import pytest

from apps.audit.models import AuditAction, AuditEvent
from apps.audit.services import record
from apps.workspaces.models import Membership
from apps.workspaces.services import create_workspace
from tests.helpers import STRONG_PASSWORD

pytestmark = pytest.mark.django_db


def events(action=None, **filters):
    queryset = AuditEvent.objects.filter(**filters)
    return queryset.filter(action=action) if action else queryset


def audit_url(ws):
    return f"/api/workspaces/{ws.pk}/audit/"


# --- events are written for each action ----------------------------------------


def test_login_is_audited(make_user, client_for):
    user = make_user("ada")
    response = client_for().post(
        "/api/auth/login/", {"email": user.email, "password": STRONG_PASSWORD}, format="json"
    )
    assert response.status_code == 200
    event = events(AuditAction.LOGIN).get()
    assert (event.actor, event.target_type, event.target_id) == (user, "user", str(user.pk))
    assert event.workspace is None


def test_failed_login_is_not_audited(make_user, client_for):
    user = make_user("ada")
    client_for().post("/api/auth/login/", {"email": user.email, "password": "no"}, format="json")
    assert not AuditEvent.objects.exists()


def test_logout_is_audited(make_user, client_for):
    user = make_user("ada")
    client = client_for()
    tokens = client.post(
        "/api/auth/login/", {"email": user.email, "password": STRONG_PASSWORD}, format="json"
    ).json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert client.post("/api/auth/logout/", {"refresh": tokens["refresh"]}, format="json")
    assert events(AuditAction.LOGOUT, actor=user).count() == 1


def test_password_change_is_audited_without_secrets(make_user, client_for):
    user = make_user("ada")
    client = client_for(user)
    response = client.post(
        "/api/auth/change-password/",
        {"old_password": STRONG_PASSWORD, "new_password": "Another-Str0ng-Passphrase!"},
        format="json",
    )
    assert response.status_code == 200
    event = events(AuditAction.PASSWORD_CHANGE).get()
    assert event.actor == user
    assert "password" not in str(event.metadata).lower()


def test_workspace_create_rename_delete_are_audited(make_user, client_for):
    user = make_user("ada")
    client = client_for(user)
    created = client.post("/api/workspaces/", {"name": "Acme"}, format="json").json()
    wid = created["id"]
    client.patch(f"/api/workspaces/{wid}/", {"name": "Acme Co"}, format="json")
    client.delete(f"/api/workspaces/{wid}/")

    create_event = events(AuditAction.WORKSPACE_CREATE).get()
    assert create_event.actor == user and create_event.target_id == wid
    assert create_event.metadata == {"name": "Acme"}
    update_event = events(AuditAction.WORKSPACE_UPDATE).get()
    assert update_event.metadata == {"old_name": "Acme", "new_name": "Acme Co"}
    delete_event = events(AuditAction.WORKSPACE_DELETE).get()
    assert delete_event.actor == user
    assert delete_event.workspace is None  # the workspace no longer exists
    assert delete_event.metadata == {"workspace_id": wid, "name": "Acme Co"}
    # earlier events survive the deletion, detached from the deleted workspace
    assert events(AuditAction.WORKSPACE_CREATE).get().workspace is None


def test_renaming_to_the_same_name_is_not_audited(make_user, client_for):
    user = make_user("ada")
    client = client_for(user)
    wid = client.post("/api/workspaces/", {"name": "Acme"}, format="json").json()["id"]
    client.patch(f"/api/workspaces/{wid}/", {"name": "Acme"}, format="json")
    assert not events(AuditAction.WORKSPACE_UPDATE).exists()


def test_every_membership_change_is_audited(two_workspaces, client_for):
    ws = two_workspaces["a"]["workspace"]
    owner = two_workspaces["a"]["owner"]
    newcomer = two_workspaces["outsider"]
    client = client_for(owner)
    base = f"/api/workspaces/{ws.pk}/members/"

    added = client.post(base, {"email": newcomer.email, "role": "viewer"}, format="json").json()
    client.patch(f"{base}{added['id']}/", {"role": "analyst"}, format="json")
    client.delete(f"{base}{added['id']}/")
    viewer = Membership.objects.get(user=two_workspaces["a"]["viewer"], workspace=ws)
    client_for(two_workspaces["a"]["viewer"]).post(base + "leave/")

    add = events(AuditAction.MEMBER_ADD, workspace=ws).get()
    assert add.actor == owner and add.target_id == added["id"]
    assert add.metadata == {"user_id": str(newcomer.pk), "email": newcomer.email, "role": "viewer"}
    change = events(AuditAction.MEMBER_ROLE_CHANGE, workspace=ws).get()
    assert change.metadata["old_role"] == "viewer" and change.metadata["new_role"] == "analyst"
    remove = events(AuditAction.MEMBER_REMOVE, workspace=ws).get()
    assert remove.actor == owner and remove.metadata["role"] == "analyst"
    leave = events(AuditAction.MEMBER_LEAVE, workspace=ws).get()
    assert leave.actor == two_workspaces["a"]["viewer"]
    assert leave.target_id == str(viewer.pk)


def test_refused_changes_write_no_event(make_user, client_for):
    owner = make_user("ada")
    ws = create_workspace(user=owner, name="Acme")
    AuditEvent.objects.all().delete()
    membership = Membership.objects.get(user=owner, workspace=ws)
    response = client_for(owner).patch(
        f"/api/workspaces/{ws.pk}/members/{membership.pk}/", {"role": "viewer"}, format="json"
    )
    assert response.status_code == 409
    assert not AuditEvent.objects.exists()


def test_events_are_append_only(make_user):
    event = record(AuditAction.LOGIN, actor=make_user("ada"))
    event.target_type = "tampered"
    with pytest.raises(RuntimeError):
        event.save()


def test_events_survive_deleting_the_actor(make_user):
    user = make_user("ada")
    event = record(AuditAction.LOGIN, actor=user)
    user.delete()
    event.refresh_from_db()
    assert event.actor is None


def test_str(make_user):
    assert "auth.login" in str(record(AuditAction.LOGIN, actor=make_user("ada")))


# --- read API: owners only --------------------------------------------------------


def test_owner_reads_the_workspace_log_newest_first(two_workspaces, client_for):
    a = two_workspaces["a"]
    client = client_for(a["owner"])
    client.post(
        f"/api/workspaces/{a['workspace'].pk}/members/",
        {"email": two_workspaces["outsider"].email, "role": "viewer"},
        format="json",
    )
    response = client.get(audit_url(a["workspace"]))
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [r["action"] for r in rows] == ["member.add", "workspace.create"]
    assert rows[0]["actor"] == {"id": str(a["owner"].pk), "email": a["owner"].email}
    assert set(rows[0]) == {
        "id",
        "action",
        "actor",
        "target_type",
        "target_id",
        "metadata",
        "created_at",
    }


def test_log_can_be_filtered_by_action(two_workspaces, client_for):
    a = two_workspaces["a"]
    record(AuditAction.MEMBER_ADD, workspace=a["workspace"], actor=a["owner"])
    record(AuditAction.MEMBER_LEAVE, workspace=a["workspace"], actor=a["owner"])
    response = client_for(a["owner"]).get(audit_url(a["workspace"]) + "?action=member.leave")
    assert [r["action"] for r in response.json()["results"]] == ["member.leave"]


def test_log_only_contains_the_requested_workspace(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    record(AuditAction.MEMBER_ADD, workspace=b["workspace"], actor=b["owner"], secret="b-only")
    response = client_for(a["owner"]).get(audit_url(a["workspace"]))
    assert "b-only" not in response.content.decode()


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_non_owner_members_get_403(two_workspaces, client_for, role):
    a = two_workspaces["a"]
    event = record(AuditAction.MEMBER_ADD, workspace=a["workspace"], actor=a["owner"])
    client = client_for(a[role])
    assert client.get(audit_url(a["workspace"])).status_code == 403
    assert client.get(f"{audit_url(a['workspace'])}{event.pk}/").status_code == 403


def test_non_members_get_404_and_anonymous_401(two_workspaces, client_for):
    a = two_workspaces["a"]
    event = record(AuditAction.MEMBER_ADD, workspace=a["workspace"], actor=a["owner"])
    stranger = client_for(two_workspaces["b"]["owner"])
    assert stranger.get(audit_url(a["workspace"])).status_code == 404
    assert stranger.get(f"{audit_url(a['workspace'])}{event.pk}/").status_code == 404
    assert client_for().get(audit_url(a["workspace"])).status_code == 401


def test_owner_cannot_read_another_workspaces_event_by_id(two_workspaces, client_for):
    a, b = two_workspaces["a"], two_workspaces["b"]
    event = record(AuditAction.MEMBER_ADD, workspace=b["workspace"], actor=b["owner"])
    response = client_for(a["owner"]).get(f"{audit_url(a['workspace'])}{event.pk}/")
    assert response.status_code == 404


def test_owner_retrieves_one_event(two_workspaces, client_for):
    a = two_workspaces["a"]
    event = record(AuditAction.MEMBER_ADD, workspace=a["workspace"], actor=a["owner"], k="v")
    response = client_for(a["owner"]).get(f"{audit_url(a['workspace'])}{event.pk}/")
    assert response.status_code == 200
    assert response.json()["metadata"] == {"k": "v"}


def test_log_is_read_only(two_workspaces, client_for):
    a = two_workspaces["a"]
    event = record(AuditAction.MEMBER_ADD, workspace=a["workspace"], actor=a["owner"])
    client = client_for(a["owner"])
    detail = f"{audit_url(a['workspace'])}{event.pk}/"
    # unrouted methods are rejected (denied by the permission layer before routing)
    assert client.post(audit_url(a["workspace"]), {}, format="json").status_code in (403, 405)
    assert client.patch(detail, {"action": "x"}, format="json").status_code in (403, 405)
    assert client.delete(detail).status_code in (403, 405)
    event.refresh_from_db()
    assert event.action == AuditAction.MEMBER_ADD
    assert AuditEvent.objects.filter(pk=event.pk).exists()
