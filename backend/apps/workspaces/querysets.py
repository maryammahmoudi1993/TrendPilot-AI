from django.db import models


class WorkspaceScopedQuerySet(models.QuerySet):
    """For models with a ``workspace`` foreign key."""

    def for_user(self, user):
        """Rows in workspaces where ``user`` is a member."""
        if user is None or not user.is_authenticated:
            return self.none()
        return self.filter(workspace__memberships__user=user)

    def for_workspace(self, workspace):
        return self.filter(workspace=workspace)


WorkspaceScopedManager = models.Manager.from_queryset(WorkspaceScopedQuerySet)
