# Roles and permissions

Every workspace member has exactly one role: **Owner**, **Analyst** or **Viewer**.
The matrix below is enforced in code by `apps/workspaces/matrix.py`
(`PERMISSION_MATRIX`) and checked against this table by a test.

| Action | Owner | Analyst | Viewer |
| --- | --- | --- | --- |
| view | yes | yes | yes |
| create | yes | yes | no |
| edit | yes | yes | no |
| delete | yes | yes | no |
| edit_workspace | yes | no | no |
| manage_members | yes | no | no |
| delete_workspace | yes | no | no |
| view_audit | yes | no | no |

- `view`, `create`, `edit`, `delete` apply to data inside a workspace (datasets,
  models, forecasts, ...). "Upload" is a `create`.
- `edit_workspace` is renaming the workspace; `manage_members` is adding, changing the
  role of and removing members (any member may list members and leave); `delete_workspace` deletes it;
  `view_audit` reads the workspace audit log (`/api/workspaces/{id}/audit/`).

## Non-members get 404, members without the role get 403

A user who is not a member of a workspace gets **404** on every resource that
belongs to it, including nested routes, so the existence of a workspace or of an
object inside it is never leaked. A member whose role lacks the action gets **403**.
Unauthenticated requests get **401**.

## Building blocks for new apps

`apps/workspaces/scoping.py` provides everything a workspace-scoped app needs:

```python
from apps.workspaces.scoping import (
    WorkspaceScopedModel, WorkspaceScopedViewSetMixin, workspace_prefix,
)

class Dataset(WorkspaceScopedModel):          # adds id, workspace FK, timestamps
    name = models.CharField(max_length=120)   # and objects.for_user()/for_workspace()

class DatasetViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Dataset.objects.all()
    serializer_class = DatasetSerializer

router.register(workspace_prefix("datasets"), DatasetViewSet, basename="dataset")
# -> /api/workspaces/{workspace_id}/datasets/
```

The mixin resolves the caller's membership (404 if none), filters the queryset to
that workspace, stamps `workspace` on create and applies the matrix. Custom DRF
actions are mapped with `required_actions = {"my_action": Action.EDIT}`; an
unmapped unsafe action is denied.

Serializers must never accept a client-supplied `workspace` or foreign keys to
objects in another workspace without checking them against the caller's workspace.

## Member management rules

Endpoints under `/api/workspaces/{id}/members/`:

| Endpoint | Who |
| --- | --- |
| `GET members/` | any member |
| `POST members/` (add by email of an existing, active user, with a role) | Owner |
| `PATCH members/{membership_id}/` (change role) | Owner |
| `DELETE members/{membership_id}/` (remove) | Owner |
| `POST members/leave/` | any member |

- A workspace always keeps at least one Owner: demoting, removing or leaving as the
  last Owner returns `409` with error code `last_owner`.
- Ownership transfer: promote another member to Owner, then demote yourself (or leave).
- Membership changes take a row lock on the workspace inside a transaction, so two
  owners removing each other at the same moment cannot leave the workspace ownerless.

## Isolation suite (required for every new workspace-scoped model)

`backend/tests/isolation.py` holds a registry of workspace-scoped resources and
`backend/tests/test_isolation_suite.py` runs, for each of them, the same checks over the
`two_workspaces` fixture (two workspaces, an Owner, an Analyst and a Viewer in each,
plus an outsider): 401 for anonymous callers, the role matrix (403 and unchanged data
when refused), 404 for non-members, 404 for another workspace's object id addressed
through your own workspace (also when you are a member of both), and lists that never
contain other workspaces' rows. A meta-test fails if a model with a `workspace`
foreign key is not registered.

To add a model: write an `IsolatedResource` (list URL, object factory, supported
operations mapped to matrix actions, payloads) and `register()` it.
