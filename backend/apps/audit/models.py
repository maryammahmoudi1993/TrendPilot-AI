import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import Workspace
from apps.workspaces.querysets import WorkspaceScopedManager


class AuditAction(models.TextChoices):
    LOGIN = "auth.login", "Login"
    LOGOUT = "auth.logout", "Logout"
    PASSWORD_CHANGE = "auth.password_change", "Password change"
    WORKSPACE_CREATE = "workspace.create", "Workspace created"
    WORKSPACE_UPDATE = "workspace.update", "Workspace renamed"
    WORKSPACE_DELETE = "workspace.delete", "Workspace deleted"
    MEMBER_ADD = "member.add", "Member added"
    MEMBER_ROLE_CHANGE = "member.role_change", "Member role changed"
    MEMBER_REMOVE = "member.remove", "Member removed"
    MEMBER_LEAVE = "member.leave", "Member left"


class AuditEvent(models.Model):
    """Append-only record of a security-relevant action.

    ``workspace`` is null for account events and for workspace deletion (the workspace
    is gone; its id and name are kept in ``metadata``). Rows survive deletion of the
    actor or the workspace.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    action = models.CharField(max_length=40, choices=AuditAction.choices)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "-created_at"], name="audit_ws_created_idx")]

    def __str__(self):
        return f"{self.action} by {self.actor_id} at {self.created_at:%Y-%m-%d %H:%M:%S}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit events are append-only.")
        super().save(*args, **kwargs)
