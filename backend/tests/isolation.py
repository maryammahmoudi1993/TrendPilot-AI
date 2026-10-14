"""Registry of workspace-scoped resources that must pass the isolation suite.

Every model with a ``workspace`` foreign key MUST be registered here (a meta-test in
``test_isolation_suite.py`` fails otherwise). The suite then proves, for each resource:

* anonymous callers get 401,
* each role (owner / analyst / viewer) can do exactly what the permission matrix allows
  and a refused action leaves the data untouched (403),
* non-members, including members of *another* workspace, get 404 on every operation,
* another workspace's object id addressed through the caller's own workspace path is 404,
* list endpoints never include rows of other workspaces.

To add a resource, build an ``IsolatedResource`` and call ``register`` (see the bottom of
this file). ``ctx`` is the ``two_workspaces`` fixture value::

    {"a": {"workspace", "owner", "analyst", "viewer"}, "b": {...}, "outsider": user}
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditAction, AuditEvent
from apps.audit.services import record
from apps.datasets.models import Dataset
from apps.workspaces.matrix import Action
from apps.workspaces.models import Membership
from tests.probe_app.models import Probe

OPS = ("list", "retrieve", "create", "update", "delete")
SUCCESS_STATUS = {"list": 200, "retrieve": 200, "create": 201, "update": 200, "delete": 204}


@dataclass
class IsolatedResource:
    name: str
    model: type
    list_url: Callable  # workspace -> url of the collection (with trailing slash)
    make: Callable  # (workspace, ctx) -> an existing object in that workspace
    ops: dict[str, Action]  # supported operations -> action required by the matrix
    create_payload: Callable = lambda ctx: {}  # noqa: E731
    update_payload: Callable = lambda ctx: {}  # noqa: E731
    changed: tuple[str, object] | None = None  # (field, value) an allowed update must set
    extra: dict = field(default_factory=dict)  # {"multipart": True} for file-upload creates

    def __str__(self):
        return self.name


REGISTRY: list[IsolatedResource] = []


def register(resource: IsolatedResource) -> IsolatedResource:
    REGISTRY.append(resource)
    return resource


def registered_models() -> set[type]:
    return {r.model for r in REGISTRY}


def workspace_models_in_project() -> set[type]:
    """Every installed model that carries a ``workspace`` foreign key."""
    from django.apps import apps

    return {
        model
        for model in apps.get_models()
        if any(f.name == "workspace" and f.is_relation for f in model._meta.get_fields())
    }


# --- registrations -------------------------------------------------------------------

register(
    IsolatedResource(
        name="probe",
        model=Probe,
        list_url=lambda ws: f"/api/workspaces/{ws.pk}/probes/",
        make=lambda ws, ctx: Probe.objects.create(workspace=ws, name="seed"),
        ops={
            "list": Action.VIEW,
            "retrieve": Action.VIEW,
            "create": Action.CREATE,
            "update": Action.EDIT,
            "delete": Action.DELETE,
        },
        create_payload=lambda ctx: {"name": "new"},
        update_payload=lambda ctx: {"name": "changed"},
        changed=("name", "changed"),
    )
)

register(
    IsolatedResource(
        name="members",
        model=Membership,
        list_url=lambda ws: f"/api/workspaces/{ws.pk}/members/",
        make=lambda ws, ctx: Membership.objects.get(workspace=ws, role="viewer"),
        ops={
            "list": Action.VIEW,
            "create": Action.MANAGE_MEMBERS,
            "update": Action.MANAGE_MEMBERS,
            "delete": Action.MANAGE_MEMBERS,
        },
        create_payload=lambda ctx: {"email": ctx["outsider"].email, "role": "viewer"},
        update_payload=lambda ctx: {"role": "analyst"},
        changed=("role", "analyst"),
    )
)

register(
    IsolatedResource(
        name="audit",
        model=AuditEvent,
        list_url=lambda ws: f"/api/workspaces/{ws.pk}/audit/",
        make=lambda ws, ctx: record(AuditAction.MEMBER_ADD, workspace=ws, actor=ctx["a"]["owner"]),
        ops={"list": Action.VIEW_AUDIT, "retrieve": Action.VIEW_AUDIT},
    )
)

register(
    IsolatedResource(
        name="datasets",
        model=Dataset,
        list_url=lambda ws: f"/api/workspaces/{ws.pk}/datasets/",
        make=lambda ws, ctx: Dataset.objects.create(
            workspace=ws,
            name="seed.csv",
            original_filename="seed.csv",
            size=10,
            sha256=secrets.token_hex(32),
        ),
        ops={"list": Action.VIEW, "retrieve": Action.VIEW, "create": Action.CREATE},
        create_payload=lambda ctx: {
            "name": "new.csv",
            "file": SimpleUploadedFile(
                "new.csv", b"date,value\n2024-01-01,1\n", content_type="text/csv"
            ),
        },
        extra={"multipart": True},
    )
)
