from django.db import models

from apps.workspaces.scoping import WorkspaceScopedModel


class Probe(WorkspaceScopedModel):
    name = models.CharField(max_length=80)
