"""The role x action permission matrix. Documented in docs/permissions.md."""

from enum import StrEnum

from .models import Role


class Action(StrEnum):
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    EDIT_WORKSPACE = "edit_workspace"
    MANAGE_MEMBERS = "manage_members"
    DELETE_WORKSPACE = "delete_workspace"
    VIEW_AUDIT = "view_audit"


ALL_ROLES = frozenset(Role.values)
WRITERS = frozenset({Role.OWNER, Role.ANALYST})
OWNER_ONLY = frozenset({Role.OWNER})

PERMISSION_MATRIX: dict[Action, frozenset[str]] = {
    Action.VIEW: ALL_ROLES,
    Action.CREATE: WRITERS,
    Action.EDIT: WRITERS,
    Action.DELETE: WRITERS,
    Action.EDIT_WORKSPACE: OWNER_ONLY,
    Action.MANAGE_MEMBERS: OWNER_ONLY,
    Action.DELETE_WORKSPACE: OWNER_ONLY,
    Action.VIEW_AUDIT: OWNER_ONLY,
}


def can(role: str | None, action: Action) -> bool:
    """True when ``role`` may perform ``action`` inside a workspace."""
    return role in PERMISSION_MATRIX[action]
