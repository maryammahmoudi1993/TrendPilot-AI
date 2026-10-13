from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import record

from .exceptions import LastOwnerError
from .models import Membership, Role, Workspace


@transaction.atomic
def create_workspace(*, user, name: str) -> Workspace:
    """Create a workspace and make ``user`` its Owner in one transaction."""
    workspace = Workspace.objects.create(name=name, created_by=user)
    Membership.objects.create(user=user, workspace=workspace, role=Role.OWNER)
    record(
        AuditAction.WORKSPACE_CREATE,
        actor=user,
        workspace=workspace,
        target_type="workspace",
        target_id=workspace.pk,
        name=workspace.name,
    )
    return workspace


@transaction.atomic
def rename_workspace(*, workspace: Workspace, actor, name: str) -> Workspace:
    old_name = workspace.name
    if name == old_name:
        return workspace
    workspace.name = name
    workspace.save(update_fields=["name", "updated_at"])
    record(
        AuditAction.WORKSPACE_UPDATE,
        actor=actor,
        workspace=workspace,
        target_type="workspace",
        target_id=workspace.pk,
        old_name=old_name,
        new_name=name,
    )
    return workspace


@transaction.atomic
def delete_workspace(*, workspace: Workspace, actor) -> None:
    # The workspace row disappears, so the event is not linked to it; id and name
    # are kept in the metadata.
    record(
        AuditAction.WORKSPACE_DELETE,
        actor=actor,
        target_type="workspace",
        target_id=workspace.pk,
        workspace_id=str(workspace.pk),
        name=workspace.name,
    )
    workspace.delete()


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
def add_member(*, workspace: Workspace, user, role: str, actor=None) -> Membership:
    _lock_workspace(workspace.pk)
    membership = Membership.objects.create(user=user, workspace=workspace, role=role)
    record(
        AuditAction.MEMBER_ADD,
        actor=actor,
        workspace=workspace,
        target_type="membership",
        target_id=membership.pk,
        user_id=str(user.pk),
        email=user.email,
        role=role,
    )
    return membership


@transaction.atomic
def change_role(*, membership: Membership, role: str, actor=None) -> Membership:
    """Change a member's role; refuses to demote the last Owner."""
    workspace = _lock_workspace(membership.workspace_id)
    membership = Membership.objects.select_related("user").get(pk=membership.pk)
    old_role = membership.role
    if (
        old_role == Role.OWNER
        and role != Role.OWNER
        and not _other_owner_exists(membership.workspace_id, membership.pk)
    ):
        raise LastOwnerError()
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    record(
        AuditAction.MEMBER_ROLE_CHANGE,
        actor=actor,
        workspace=workspace,
        target_type="membership",
        target_id=membership.pk,
        user_id=str(membership.user_id),
        email=membership.user.email,
        old_role=old_role,
        new_role=role,
    )
    return membership


@transaction.atomic
def remove_member(*, membership: Membership, actor=None, voluntary: bool = False) -> None:
    """Remove a member (``voluntary``: they left); refuses to remove the last Owner."""
    workspace = _lock_workspace(membership.workspace_id)
    membership = Membership.objects.select_related("user").get(pk=membership.pk)
    if membership.role == Role.OWNER and not _other_owner_exists(
        membership.workspace_id, membership.pk
    ):
        raise LastOwnerError()
    record(
        AuditAction.MEMBER_LEAVE if voluntary else AuditAction.MEMBER_REMOVE,
        actor=actor,
        workspace=workspace,
        target_type="membership",
        target_id=membership.pk,
        user_id=str(membership.user_id),
        email=membership.user.email,
        role=membership.role,
    )
    membership.delete()
