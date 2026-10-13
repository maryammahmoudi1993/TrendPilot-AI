from django.db import transaction

from .exceptions import LastOwnerError
from .models import Membership, Role, Workspace


@transaction.atomic
def create_workspace(*, user, name: str) -> Workspace:
    """Create a workspace and make ``user`` its Owner in one transaction."""
    workspace = Workspace.objects.create(name=name, created_by=user)
    Membership.objects.create(user=user, workspace=workspace, role=Role.OWNER)
    return workspace


def _lock_workspace(workspace_id) -> Workspace:
    """Serialise membership changes per workspace (row lock; held until commit)."""
    return Workspace.objects.select_for_update().get(pk=workspace_id)


def _other_owner_exists(workspace_id, excluding_membership_id) -> bool:
    return (
        Membership.objects.filter(workspace_id=workspace_id, role=Role.OWNER)
        .exclude(pk=excluding_membership_id)
        .exists()
    )


@transaction.atomic
def add_member(*, workspace: Workspace, user, role: str) -> Membership:
    _lock_workspace(workspace.pk)
    return Membership.objects.create(user=user, workspace=workspace, role=role)


@transaction.atomic
def change_role(*, membership: Membership, role: str) -> Membership:
    """Change a member's role; refuses to demote the last Owner."""
    _lock_workspace(membership.workspace_id)
    membership = Membership.objects.select_related("user").get(pk=membership.pk)
    if (
        membership.role == Role.OWNER
        and role != Role.OWNER
        and not _other_owner_exists(membership.workspace_id, membership.pk)
    ):
        raise LastOwnerError()
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    return membership


@transaction.atomic
def remove_member(*, membership: Membership) -> None:
    """Remove a member (or let them leave); refuses to remove the last Owner."""
    _lock_workspace(membership.workspace_id)
    membership = Membership.objects.get(pk=membership.pk)
    if membership.role == Role.OWNER and not _other_owner_exists(
        membership.workspace_id, membership.pk
    ):
        raise LastOwnerError()
    membership.delete()
