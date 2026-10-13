from rest_framework.permissions import SAFE_METHODS, BasePermission

from .matrix import Action, can

DEFAULT_ACTIONS = {
    "list": Action.VIEW,
    "retrieve": Action.VIEW,
    "create": Action.CREATE,
    "update": Action.EDIT,
    "partial_update": Action.EDIT,
    "destroy": Action.DELETE,
}


class WorkspaceObjectPermission(BasePermission):
    """Permission for the workspace resource itself (``obj.role`` is the caller's role)."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return can(obj.role, Action.VIEW)
        if request.method == "DELETE":
            return can(obj.role, Action.DELETE_WORKSPACE)
        return can(obj.role, Action.EDIT_WORKSPACE)


class WorkspaceRolePermission(BasePermission):
    """Role check for views using ``WorkspaceScopedViewSetMixin``.

    A non-member never gets here with a 403: resolving the membership raises 404 so the
    existence of a workspace is not leaked. Members whose role lacks the required action
    get 403. Views map custom DRF actions through ``required_actions``; an unmapped
    unsafe action is denied.
    """

    def has_permission(self, request, view):
        membership = view.get_membership()
        required = {**DEFAULT_ACTIONS, **getattr(view, "required_actions", {})}.get(view.action)
        if required is None:
            required = Action.VIEW if request.method in SAFE_METHODS else None
        return required is not None and can(membership.role, required)
