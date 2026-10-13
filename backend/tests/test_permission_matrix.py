import re
from pathlib import Path

import pytest

from apps.workspaces.matrix import PERMISSION_MATRIX, Action, can
from apps.workspaces.models import Role

DOC = Path(__file__).resolve().parents[2] / "docs" / "permissions.md"


def documented_matrix() -> dict[str, set[str]]:
    rows = re.findall(r"^\| (\w+) \| (yes|no) \| (yes|no) \| (yes|no) \|$", DOC.read_text(), re.M)
    roles = [Role.OWNER, Role.ANALYST, Role.VIEWER]
    return {
        action: {role for role, cell in zip(roles, cells, strict=True) if cell == "yes"}
        for action, *cells in rows
    }


def test_every_action_is_in_the_matrix():
    assert set(PERMISSION_MATRIX) == set(Action)


def test_docs_table_matches_the_code():
    assert documented_matrix() == {a.value: set(r) for a, r in PERMISSION_MATRIX.items()}


@pytest.mark.parametrize("action", list(Action))
def test_owner_can_do_everything(action):
    assert can(Role.OWNER, action)


@pytest.mark.parametrize("action", [Action.EDIT_WORKSPACE, Action.MANAGE_MEMBERS])
def test_analyst_cannot_manage_members_or_workspace(action):
    assert not can(Role.ANALYST, action)
    assert not can(Role.ANALYST, Action.DELETE_WORKSPACE)


@pytest.mark.parametrize(
    "action", [Action.CREATE, Action.EDIT, Action.DELETE, Action.MANAGE_MEMBERS]
)
def test_viewer_is_read_only(action):
    assert not can(Role.VIEWER, action)
    assert can(Role.VIEWER, Action.VIEW)


def test_no_role_means_no_access():
    assert not any(can(None, action) for action in Action)
