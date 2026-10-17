import threading
import uuid
from datetime import date, timedelta

import pytest
from django.core.files.base import ContentFile
from django.db import connection, connections
from django.utils import timezone

from apps.audit.models import AuditAction, AuditEvent
from apps.datasets.models import Dataset, DatasetStatus
from apps.datasets.services import run_validation, start_validation, update_mapping
from apps.datasets.tasks import validate_dataset
from tests.helpers import make_dataset

pytestmark = pytest.mark.django_db


def _daily(n, start=date(2024, 1, 1)):
    rows = (f"{start + timedelta(days=i)},{100 + i % 7}" for i in range(n))
    return "date,sales\n" + "\n".join(rows) + "\n"


GOOD = _daily(120)
TINY = "date,sales\n" + "".join(f"2024-01-{1 + i:02d},{10 + i}\n" for i in range(5))


@pytest.fixture
def ctx(two_workspaces, client_for):
    return {"ws": two_workspaces["a"]["workspace"], "users": two_workspaces, "client": client_for}


def make(ws, text=GOOD, mapped=True, sha=None):
    dataset = make_dataset(ws, text, sha=sha or uuid.uuid4().hex * 2)
    if mapped:
        update_mapping(
            dataset=dataset, actor=None, data={"date": "date", "target": "sales"}, partial=False
        )
        dataset.refresh_from_db()
    return dataset


def url(ws, dataset, tail="validate/"):
    return f"/api/workspaces/{ws.pk}/datasets/{dataset.pk}/{tail}"


@pytest.fixture
def post(ctx, django_capture_on_commit_callbacks):
    """POST /validate/; ``run=True`` also executes the queued task (after the commit)."""

    def call(dataset, user=None, run=True):
        client = ctx["client"](user or ctx["users"]["a"]["owner"])
        with django_capture_on_commit_callbacks(execute=run):
            return client.post(url(ctx["ws"], dataset))

    return call


def audit_phases(dataset):
    events = AuditEvent.objects.filter(
        action=AuditAction.DATASET_VALIDATE, target_id=str(dataset.pk)
    ).order_by("created_at", "id")
    return [e.metadata["phase"] for e in events]


# --- happy path -----------------------------------------------------------------------------


def test_validate_returns_202_validating_then_the_task_stores_the_report(ctx, post):
    dataset = make(ctx["ws"])
    response = post(dataset)
    assert response.status_code == 202, response.content
    assert response.json()["status"] == "validating"
    assert response.json()["quality_report"] is None

    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATED
    assert dataset.quality_report["schema_version"] == 1
    assert dataset.quality_report["overview"]["rows"] == 120
    assert dataset.validated_at is not None
    assert dataset.validation_error == "" and dataset.validation_run is None


def test_the_detail_endpoint_polls_the_result(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset)
    body = ctx["client"](ctx["users"]["a"]["viewer"]).get(url(ctx["ws"], dataset, "")).json()
    assert body["status"] == "validated"
    assert body["quality_report"]["overview"]["frequency"] == "daily"
    assert body["validated_at"] and body["validation_error"] == ""


def test_the_task_is_only_queued_after_the_response_is_committed(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset, run=False)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATING
    assert dataset.quality_report is None


def test_warnings_still_give_validated(ctx, post):
    dataset = make(
        ctx["ws"], "date,sales\n" + "".join(f"2024-02-{1 + i:02d},{5 + i}\n" for i in range(20))
    )
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.quality_report["severity"] == "warning"  # series_short
    assert dataset.status == DatasetStatus.VALIDATED


# --- failures -------------------------------------------------------------------------------


def test_error_findings_that_block_modelling_give_failed_with_a_reason(ctx, post):
    dataset = make(ctx["ws"], TINY)
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED
    assert "fewer than 10" in dataset.validation_error
    assert dataset.quality_report["severity"] == "error"  # the report is kept for the user


def test_a_missing_file_is_a_clean_failure(ctx, post):
    dataset = make(ctx["ws"])
    dataset.file.storage.delete(dataset.file.name)
    assert post(dataset).status_code == 202
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED
    assert dataset.validation_error == "The dataset's file is missing from storage."
    assert dataset.quality_report is None


def test_a_crash_is_stored_without_leaking_internals(ctx, post, monkeypatch, caplog):
    def explode(dataset):
        raise RuntimeError("secret /srv/path detail")

    monkeypatch.setattr("apps.datasets.services.build_quality_report", explode)
    dataset = make(ctx["ws"])
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED
    assert "unexpected error" in dataset.validation_error
    assert "secret" not in dataset.validation_error
    assert "secret /srv/path detail" in caplog.text  # but it is logged


def test_an_unreadable_file_reports_why(ctx, post):
    dataset = make(ctx["ws"])
    with dataset.file.open("wb") as handle:
        handle.write(b"\xff\xfe\x00bad")
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED
    assert dataset.validation_error.startswith("The dataset's file could not be read")


def test_a_soft_time_limit_is_a_clean_failure(ctx, post, monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded

    def slow(dataset):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr("apps.datasets.services.build_quality_report", slow)
    dataset = make(ctx["ws"])
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED and "too long" in dataset.validation_error


def test_the_task_has_time_limits_and_late_acks():
    assert validate_dataset.soft_time_limit and validate_dataset.time_limit
    assert validate_dataset.time_limit > validate_dataset.soft_time_limit
    assert validate_dataset.acks_late is True


# --- conflicts and state rules -------------------------------------------------------------


def test_no_mapping_is_409(ctx, post):
    dataset = make(ctx["ws"], mapped=False)
    response = post(dataset)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_mapping"
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.UPLOADED


def test_double_trigger_is_409(ctx, post):
    dataset = make(ctx["ws"])
    assert post(dataset, run=False).status_code == 202
    second = post(dataset, run=False)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_validating"
    assert audit_phases(dataset) == ["started"]  # the refused request wrote nothing


def test_a_lost_run_can_be_replaced_after_the_stale_limit(ctx, post, settings):
    dataset = make(ctx["ws"])
    post(dataset, run=False)
    Dataset.objects.filter(pk=dataset.pk).update(
        updated_at=timezone.now() - timedelta(seconds=settings.DATASET_VALIDATION_STALE_SECONDS + 5)
    )
    assert post(dataset).status_code == 202
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATED


def test_revalidating_replaces_the_report(ctx, post, settings):
    dataset = make(ctx["ws"])
    post(dataset)
    dataset.refresh_from_db()
    first_report, first_at = dataset.quality_report, dataset.validated_at
    assert "series_short" not in {f["code"] for f in first_report["findings"]}

    settings.DATASET_MIN_OBSERVATIONS_WARN = 500
    assert post(dataset).status_code == 202
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATED
    assert "series_short" in {f["code"] for f in dataset.quality_report["findings"]}
    assert dataset.quality_report != first_report
    assert dataset.validated_at > first_at


def test_a_failed_dataset_can_be_validated_again(ctx, post):
    dataset = make(ctx["ws"])
    stored = dataset.file.name
    with dataset.file.open("rb") as handle:
        data = handle.read()
    dataset.file.storage.delete(stored)
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.FAILED
    assert dataset.file.storage.save(stored, ContentFile(data)) == stored
    post(dataset)
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATED and dataset.validation_error == ""


def test_changing_the_mapping_clears_the_report(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset)
    response = ctx["client"](ctx["users"]["a"]["owner"]).put(
        url(ctx["ws"], dataset, "mapping/"), {"date": "date", "target": "sales"}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["quality_report"] is None and body["validated_at"] is None
    assert body["validation_error"] == ""


def test_a_run_orphaned_by_a_mapping_change_writes_nothing(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset, run=False)
    dataset.refresh_from_db()
    old_run = str(dataset.validation_run)
    update_mapping(
        dataset=dataset, actor=None, data={"date": "date", "target": "sales"}, partial=False
    )
    assert run_validation(str(dataset.pk), old_run) == "skipped"
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.UPLOADED and dataset.quality_report is None


def test_an_older_run_cannot_overwrite_a_newer_one(ctx, django_capture_on_commit_callbacks):
    dataset = make(ctx["ws"])
    user = ctx["users"]["a"]["owner"]
    with django_capture_on_commit_callbacks(execute=False):
        start_validation(dataset=dataset, actor=user)
    dataset.refresh_from_db()
    old_run = str(dataset.validation_run)
    Dataset.objects.filter(pk=dataset.pk).update(updated_at=timezone.now() - timedelta(days=1))
    with django_capture_on_commit_callbacks(execute=True):
        start_validation(dataset=dataset, actor=user)
    dataset.refresh_from_db()
    report = dataset.quality_report
    assert run_validation(str(dataset.pk), old_run) == "skipped"
    dataset.refresh_from_db()
    assert dataset.quality_report == report


def test_the_task_is_idempotent_and_ignores_unknown_ids(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset)
    dataset.refresh_from_db()
    assert run_validation(str(dataset.pk), str(uuid.uuid4())) == "skipped"
    assert run_validation(str(uuid.uuid4()), str(uuid.uuid4())) == "skipped"
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.VALIDATED


# --- audit ----------------------------------------------------------------------------------


def test_audit_events_for_start_and_completion(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset)
    events = list(
        AuditEvent.objects.filter(action=AuditAction.DATASET_VALIDATE).order_by("created_at", "id")
    )
    assert [e.metadata["phase"] for e in events] == ["started", "completed"]
    started, completed = events
    assert started.actor == ctx["users"]["a"]["owner"] and completed.actor is None
    assert started.workspace == ctx["ws"] and started.target_id == str(dataset.pk)
    assert completed.metadata["status"] == "validated"
    assert completed.metadata["severity"] == "ok"
    assert completed.metadata["dataset_name"] == dataset.name


def test_audit_event_for_a_failure_carries_the_reason(ctx, post):
    dataset = make(ctx["ws"], TINY)
    post(dataset)
    failed = AuditEvent.objects.filter(action=AuditAction.DATASET_VALIDATE).first()
    assert failed.metadata["phase"] == "failed"
    assert failed.metadata["status"] == "failed"
    assert "fewer than 10" in failed.metadata["reason"]


# --- roles and scoping ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "expected"),
    [("owner", 202), ("analyst", 202), ("viewer", 403)],
)
def test_role_matrix(ctx, post, who, expected):
    dataset = make(ctx["ws"])
    response = post(dataset, user=ctx["users"]["a"][who], run=False)
    assert response.status_code == expected
    dataset.refresh_from_db()
    assert (dataset.status == DatasetStatus.VALIDATING) is (expected == 202)


def test_a_viewer_refusal_changes_nothing_and_writes_no_audit(ctx, post):
    dataset = make(ctx["ws"])
    post(dataset, user=ctx["users"]["a"]["viewer"])
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.UPLOADED
    assert audit_phases(dataset) == []


@pytest.mark.parametrize("who", ["outsider", "b_owner"])
def test_non_members_get_404(ctx, post, who):
    dataset = make(ctx["ws"])
    user = ctx["users"]["outsider"] if who == "outsider" else ctx["users"]["b"]["owner"]
    assert post(dataset, user=user).status_code == 404
    dataset.refresh_from_db()
    assert dataset.status == DatasetStatus.UPLOADED


def test_anonymous_gets_401(ctx):
    dataset = make(ctx["ws"])
    assert ctx["client"]().post(url(ctx["ws"], dataset)).status_code == 401


def test_another_workspaces_dataset_is_404_through_my_path(ctx, post):
    foreign = make(ctx["users"]["b"]["workspace"])
    response = ctx["client"](ctx["users"]["a"]["owner"]).post(
        f"/api/workspaces/{ctx['ws'].pk}/datasets/{foreign.pk}/validate/"
    )
    assert response.status_code == 404
    random_id = ctx["client"](ctx["users"]["a"]["owner"]).post(
        f"/api/workspaces/{ctx['ws'].pk}/datasets/{uuid.uuid4()}/validate/"
    )
    assert random_id.status_code == 404 and random_id.json() == response.json()


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_validate_only_accepts_post(ctx, method):
    dataset = make(ctx["ws"])
    response = getattr(ctx["client"](ctx["users"]["a"]["owner"]), method)(url(ctx["ws"], dataset))
    assert response.status_code in (403, 405)


# --- concurrency (row locks need PostgreSQL) -----------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="row locks need PostgreSQL (CI and docker)"
)
def test_simultaneous_triggers_start_exactly_one_run(two_workspaces, monkeypatch):
    monkeypatch.setattr(validate_dataset, "delay", lambda *args: None)  # keep it 'validating'
    dataset = make(two_workspaces["a"]["workspace"])
    user = two_workspaces["a"]["owner"]
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        try:
            barrier.wait(timeout=10)
            start_validation(dataset=dataset, actor=user)
            outcomes.append("started")
        except Exception as exc:
            outcomes.append(getattr(exc, "default_code", type(exc).__name__))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["already_validating", "started"]
    assert audit_phases(dataset) == ["started"]
