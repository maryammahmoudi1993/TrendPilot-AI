import pytest
from django.db import IntegrityError, transaction

from apps.workspaces.models import Membership, Role, Workspace
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


def test_creating_a_workspace_makes_the_creator_owner(make_user):
    user = make_user("ada")
    workspace = create_workspace(user=user, name="Acme Sales")
    membership = Membership.objects.get(workspace=workspace)
    assert (membership.user, membership.role) == (user, Role.OWNER)
    assert workspace.created_by == user


def test_workspace_creation_is_atomic(make_user, monkeypatch):
    user = make_user("ada")

    def boom(*args, **kwargs):
        raise RuntimeError("membership failed")

    monkeypatch.setattr(Membership.objects, "create", boom)
    with pytest.raises(RuntimeError):
        create_workspace(user=user, name="Acme")
    assert not Workspace.objects.exists()


def test_slug_is_generated_and_unique(make_user):
    user = make_user("ada")
    slugs = [create_workspace(user=user, name="Acme Sales!").slug for _ in range(3)]
    assert slugs == ["acme-sales", "acme-sales-2", "acme-sales-3"]


def test_slug_fallback_for_names_without_letters(make_user):
    assert create_workspace(user=make_user("ada"), name="!!!").slug == "workspace"


def test_slug_is_stable_when_renamed(make_user):
    workspace = create_workspace(user=make_user("ada"), name="Acme")
    workspace.name = "Renamed"
    workspace.save()
    workspace.refresh_from_db()
    assert workspace.slug == "acme"


def test_slug_uniqueness_enforced_by_database(make_user):
    create_workspace(user=make_user("ada"), name="Acme")
    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.bulk_create([Workspace(name="Other", slug="acme")])


def test_user_can_only_have_one_membership_per_workspace(make_user):
    user = make_user("ada")
    workspace = create_workspace(user=user, name="Acme")
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, workspace=workspace, role=Role.VIEWER)


def test_deleting_a_workspace_cascades_memberships(make_user):
    owner, other = make_user("ada"), make_user("grace")
    workspace = create_workspace(user=owner, name="Acme")
    Membership.objects.create(user=other, workspace=workspace, role=Role.VIEWER)
    keep = create_workspace(user=owner, name="Keep")
    workspace.delete()
    assert not Membership.objects.filter(workspace_id=workspace.pk).exists()
    assert Membership.objects.filter(workspace=keep).count() == 1


def test_deleting_the_creator_keeps_the_workspace(make_user):
    other = make_user("grace")
    workspace = create_workspace(user=make_user("ada"), name="Acme")
    Membership.objects.create(user=other, workspace=workspace, role=Role.OWNER)
    workspace.created_by.delete()
    workspace.refresh_from_db()
    assert workspace.created_by is None
    assert workspace.memberships.count() == 1


def test_str(make_user):
    user = make_user("ada")
    workspace = create_workspace(user=user, name="Acme")
    assert str(workspace) == "Acme"
    assert "owner" in str(workspace.memberships.get())
