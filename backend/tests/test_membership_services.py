import threading

import pytest
from django.db import connection, connections

from apps.workspaces.exceptions import LastOwnerError
from apps.workspaces.models import Membership, Role
from apps.workspaces.services import add_member, change_role, create_workspace, remove_member


@pytest.fixture
def workspace_with_two_owners(make_user):
    first, second = make_user("first"), make_user("second")
    workspace = create_workspace(user=first, name="Acme")
    add_member(workspace=workspace, user=second, role=Role.OWNER)
    return workspace, first, second


@pytest.mark.django_db
class TestRules:
    def test_add_member(self, make_user):
        owner, newcomer = make_user("owner"), make_user("new")
        workspace = create_workspace(user=owner, name="Acme")
        membership = add_member(workspace=workspace, user=newcomer, role=Role.VIEWER)
        assert membership.role == Role.VIEWER

    def test_change_role_refetches_so_stale_instances_cannot_bypass_the_rule(self, make_user):
        first, second = make_user("first"), make_user("second")
        workspace = create_workspace(user=first, name="Acme")
        second_membership = add_member(workspace=workspace, user=second, role=Role.OWNER)
        first_membership = Membership.objects.get(user=first, workspace=workspace)
        stale = Membership.objects.get(pk=second_membership.pk)  # loaded while 2 owners existed
        change_role(membership=first_membership, role=Role.VIEWER)  # now only `second` is owner
        with pytest.raises(LastOwnerError):
            change_role(membership=stale, role=Role.VIEWER)

    def test_remove_last_owner_refused_but_non_owner_removed(self, make_user):
        owner, viewer = make_user("owner"), make_user("viewer")
        workspace = create_workspace(user=owner, name="Acme")
        viewer_membership = add_member(workspace=workspace, user=viewer, role=Role.VIEWER)
        owner_membership = Membership.objects.get(user=owner, workspace=workspace)
        with pytest.raises(LastOwnerError):
            remove_member(membership=owner_membership)
        remove_member(membership=viewer_membership)
        assert Membership.objects.filter(workspace=workspace).count() == 1

    def test_failed_demotion_changes_nothing(self, make_user):
        owner = make_user("owner")
        workspace = create_workspace(user=owner, name="Acme")
        membership = Membership.objects.get(user=owner, workspace=workspace)
        with pytest.raises(LastOwnerError):
            change_role(membership=membership, role=Role.ANALYST)
        membership.refresh_from_db()
        assert membership.role == Role.OWNER


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="row locks need PostgreSQL (CI and docker)"
)
@pytest.mark.parametrize("operation", ["demote", "remove"])
def test_concurrent_removal_of_both_owners_keeps_one(workspace_with_two_owners, operation):
    """Each owner tries to get rid of the other at the same moment: exactly one wins."""
    workspace, first, second = workspace_with_two_owners
    targets = [
        Membership.objects.get(user=second, workspace=workspace),
        Membership.objects.get(user=first, workspace=workspace),
    ]
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(target):
        try:
            barrier.wait(timeout=10)
            if operation == "demote":
                change_role(membership=target, role=Role.VIEWER)
            else:
                remove_member(membership=target)
            outcomes.append("ok")
        except LastOwnerError:
            outcomes.append("refused")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(t,)) for t in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["ok", "refused"]
    assert Membership.objects.filter(workspace=workspace, role=Role.OWNER).count() == 1
