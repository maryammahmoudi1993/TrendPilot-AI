from celery import shared_task
from django.conf import settings

from .services import run_validation


@shared_task(
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=settings.DATASET_VALIDATION_SOFT_TIME_LIMIT,
    time_limit=settings.DATASET_VALIDATION_TIME_LIMIT,
)
def validate_dataset(dataset_id: str, run_id: str) -> str:
    """Build and store a dataset's quality report; see ``services.run_validation``."""
    return run_validation(dataset_id, run_id)
