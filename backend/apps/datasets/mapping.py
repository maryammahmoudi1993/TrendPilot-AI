"""Validate and resolve a dataset's column mapping against the stored CSV.

Roles: ``date`` (required), ``target`` (required), ``series_id`` (optional) and
``regressors`` (optional list). The date column must parse under one explicit format
(see ``dates``); the target and regressors must be numeric (see ``numbers``). Every
problem found is returned together under ``details`` keyed by role.
"""

from collections import defaultdict

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

from .columns import read_columns
from .dates import detect_date_column
from .numbers import parse_numeric_column

ROLE_KEYS = ("date", "target", "series_id", "regressors")
OPTION_KEYS = ("date_order", "timezone", "decimal_separator")
MAX_LISTED_COLUMNS = 50


class MappingError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The column mapping is not valid for this dataset."
    default_code = "invalid_mapping"

    def __init__(self, details: dict):
        super().__init__()
        self.details = details


class DatasetFileUnavailable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The dataset's file is not available."
    default_code = "file_unavailable"


def _problem(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}


def _roles(data: dict) -> list[tuple[str, str]]:
    roles = [("date", data["date"]), ("target", data["target"])]
    if data.get("series_id"):
        roles.append(("series_id", data["series_id"]))
    roles.extend(("regressors", name) for name in data.get("regressors") or [])
    return roles


def _structure_problems(data: dict, header: list[str]) -> dict:
    problems: dict = {}
    roles = _roles(data)
    for role, name in roles:
        if name not in header:
            problems.setdefault(
                role,
                _problem(
                    "column_not_found",
                    f"Column '{name}' is not in the file.",
                    column=name,
                    available_columns=header[:MAX_LISTED_COLUMNS],
                ),
            )
        elif header.count(name) > 1:
            problems.setdefault(
                role,
                _problem(
                    "ambiguous_column",
                    f"Column '{name}' appears more than once in the header.",
                    column=name,
                ),
            )
    users = defaultdict(list)
    for role, name in roles:
        users[name].append(role)
    for name, used_by in users.items():
        if len(used_by) > 1:
            for role in dict.fromkeys(used_by):
                problems[role] = _problem(
                    "duplicate_role",
                    f"Column '{name}' cannot be used for more than one role.",
                    column=name,
                    roles=used_by,
                )
    return problems


def _numeric_problem(name: str, result, kind: str) -> dict | None:
    minimum = (
        settings.DATASET_MIN_TARGET_NUMERIC_SHARE
        if kind == "target"
        else settings.DATASET_MIN_NUMERIC_SHARE
    )
    if result.non_empty == 0:
        return _problem(
            f"{kind}_not_numeric", f"Column '{name}' has no numeric values.", column=name
        )
    share = result.converted / result.non_empty
    if share < minimum:
        return _problem(
            f"{kind}_not_numeric",
            f"Column '{name}' is not numeric: {result.failed} of {result.non_empty} "
            f"non-empty cells could not be converted.",
            column=name,
            failed=result.failed,
            examples=result.failed_examples,
        )
    return None


def resolve_mapping(dataset, data: dict) -> dict:
    """Return the ``column_mapping`` to store, or raise ``MappingError``."""
    try:
        header, columns = read_columns(dataset, [name for _, name in _roles(data)])
    except (FileNotFoundError, ValueError) as exc:
        raise DatasetFileUnavailable() from exc

    problems = _structure_problems(data, header)
    if problems:
        raise MappingError(problems)

    date_result = detect_date_column(
        columns[data["date"]], order_hint=data.get("date_order"), timezone=data.get("timezone")
    )
    if not date_result.ok:
        problems["date"] = _problem(
            date_result.code,
            date_result.message,
            column=data["date"],
            bad_count=date_result.bad_count,
            examples=date_result.bad_examples,
            **(
                {"candidate_orders": date_result.candidate_orders}
                if date_result.candidate_orders
                else {}
            ),
        )

    hint = data.get("decimal_separator")
    parsing: dict = {"date": date_result.as_dict() if date_result.ok else None}
    target = parse_numeric_column(columns[data["target"]], hint)
    parsing["target"] = target.as_dict()
    if problem := _numeric_problem(data["target"], target, "target"):
        problems["target"] = problem
    regressors = {}
    for name in data.get("regressors") or []:
        result = parse_numeric_column(columns[name], hint)
        regressors[name] = result.as_dict()
        if problem := _numeric_problem(name, result, "regressor"):
            problems.setdefault("regressors", {})[name] = problem
    parsing["regressors"] = regressors

    if problems:
        raise MappingError(problems)

    return {
        "date": data["date"],
        "target": data["target"],
        "series_id": data.get("series_id") or None,
        "regressors": list(data.get("regressors") or []),
        "date_order": data.get("date_order"),
        "timezone": data.get("timezone"),
        "decimal_separator": data.get("decimal_separator"),
        "date_format": date_result.format,
        "parsing": parsing,
    }
