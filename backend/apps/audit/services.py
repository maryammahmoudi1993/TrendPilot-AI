from .models import AuditEvent


def record(
    action: str,
    *,
    actor=None,
    workspace=None,
    target_type: str = "",
    target_id="",
    **metadata,
) -> AuditEvent:
    """Write an audit event. Call it inside the transaction of the action it describes."""
    return AuditEvent.objects.create(
        action=action,
        actor=actor,
        workspace=workspace,
        target_type=target_type,
        target_id=str(target_id),
        metadata=metadata,
    )
