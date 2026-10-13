from django.db import transaction

from .models import Membership, Role, Workspace


@transaction.atomic
def create_workspace(*, user, name: str) -> Workspace:
    """Create a workspace and make ``user`` its Owner in one transaction."""
    workspace = Workspace.objects.create(name=name, created_by=user)
    Membership.objects.create(user=user, workspace=workspace, role=Role.OWNER)
    return workspace
